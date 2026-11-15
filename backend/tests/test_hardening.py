"""Requests that lose a race or send a bad value get a clear answer, never a server error."""

import pytest
import redis.exceptions
import sqlalchemy as sa

from tests.conftest import PASSWORD, owner_engine

BODY = {
    "provider": "openai_compat",
    "model": "gpt-x",
    "base_url": "http://localhost:20128/v1",
    "api_key": "sk-secret-value-1234567890",
}


def insert_user_behind_the_requests_back(org_id, email: str) -> None:
    """Another request commits this e-mail after the request under test has checked for it."""
    engine = owner_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
        conn.execute(
            sa.text(
                "INSERT INTO users (org_id, email, name, password_hash, role) "
                "VALUES (:org, :email, 'Racer', 'not-a-hash', 'viewer')"
            ),
            {"org": str(org_id), "email": email},
        )
    engine.dispose()


async def test_create_user_that_loses_an_email_race_is_a_conflict(team, monkeypatch):
    from app.api import users as users_api

    email = "race-create@example.test"
    real_hash = users_api.hash_password

    def racing_hash(password):
        insert_user_behind_the_requests_back(team.org_id, email)
        return real_hash(password)

    monkeypatch.setattr(users_api, "hash_password", racing_hash)
    r = await team.admin.post(
        "/api/users", json={"email": email, "password": PASSWORD, "name": "Late", "role": "viewer"}
    )
    assert r.status_code == 409, r.text


async def test_signup_that_loses_an_email_race_is_a_conflict(team, client, monkeypatch):
    from app.api import auth as auth_api

    email = "race-signup@example.test"
    real_org = auth_api.Org

    def racing_org(**kwargs):  # created after signup has checked the e-mail, before it inserts the user
        insert_user_behind_the_requests_back(team.org_id, email)
        return real_org(**kwargs)

    monkeypatch.setattr(auth_api, "Org", racing_org)
    r = await client.post(
        "/api/auth/signup", json={"email": email, "password": PASSWORD, "name": "Late", "org_name": "Late Org"}
    )
    assert r.status_code == 409, r.text


async def test_an_invalid_before_is_a_422_and_a_valid_one_is_accepted(team):
    assert (await team.analyst.get("/api/runs", params={"before": "not-a-date"})).status_code == 422
    assert (await team.analyst.get("/api/runs", params={"before": "2030-01-01T00:00:00Z"})).status_code == 200
    assert (await team.analyst.get("/api/runs", params={"before": "2030-01-01"})).status_code == 200


def load_hardening_migration():
    """The migration module, loaded by path (its file name starts with a number, so it is not importable)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0009_hardening_check.py"
    spec = importlib.util.spec_from_file_location("hardening_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_database_has_the_superuser_hardening_the_migrations_check_for():
    module = load_hardening_migration()
    with owner_engine().connect() as conn:
        assert module.hardening_gaps(conn) == []


def test_init_sh_and_the_compose_file_apply_one_hardening_file():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    init = (root / "infra/postgres/init.sh").read_text()
    assert "/opt/finops/hardening.sql" in init and "set_config" not in init  # one copy of the statements
    assert (root / "infra/postgres/hardening.sql").exists()
    assert "./infra/postgres/hardening.sql:/opt/finops/hardening.sql:ro" in (root / "docker-compose.yml").read_text()


class ScriptedConnection:
    """Answers the hardening queries from a set of grants, so each kind of gap can be shown."""

    def __init__(self, grants: set[tuple[str, str]], rolconfig: list[str] | None):
        self.grants, self.rolconfig = grants, rolconfig

    def execute(self, statement, params=None):
        from types import SimpleNamespace

        sql, params = str(statement), params or {}
        if "rolconfig" in sql:
            value = self.rolconfig
        else:
            role = "finops_ro" if "'finops_ro'" in sql else "finops_app"
            value = (role, params.get("f") or params.get("v")) in self.grants
        return SimpleNamespace(scalar=lambda: value)


def test_each_missing_piece_of_the_hardening_is_reported():
    module = load_hardening_migration()
    views = module.CATALOG_VIEWS
    app_grants = {("finops_app", module.SET_CONFIG)} | {("finops_app", v) for v in views}
    ok = ScriptedConnection(app_grants, ["default_transaction_read_only=on", "statement_timeout=15s"])
    assert module.hardening_gaps(ok) == []

    leaky = ScriptedConnection(
        app_grants | {("finops_ro", module.SET_CONFIG), ("finops_ro", "pg_catalog.pg_stat_activity")},
        ["statement_timeout=15s"],
    )
    gaps = " | ".join(module.hardening_gaps(leaky))
    assert "finops_ro may call set_config" in gaps
    assert "finops_ro may read pg_catalog.pg_stat_activity" in gaps
    assert "default_transaction_read_only=on" in gaps


async def test_temperature_zero_is_sent_to_both_providers():
    import json

    import httpx

    from app.llm.anthropic import AnthropicProvider
    from app.llm.openai_compat import OpenAICompatProvider
    from app.llm.types import Message

    sent = []

    def capture(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if "/v1/messages" in str(request.url):
            return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    await OpenAICompatProvider("http://gateway.test/v1", "", transport=httpx.MockTransport(capture)).complete(
        [Message("user", "hi")], [], model="m", max_tokens=5, temperature=0
    )
    await AnthropicProvider("k", transport=httpx.MockTransport(capture)).complete(
        [Message("user", "hi")], [], model="m", max_tokens=5, temperature=0
    )
    assert [body.get("temperature") for body in sent] == [0, 0]


def test_an_unknown_llm_provider_is_a_configuration_error():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(llm_provider="openai-compatible")  # a typo must not quietly run the built-in stub


class RedisDown:
    """Every Redis call fails the way a stopped server does."""

    def pipeline(self):
        return self

    def zremrangebyscore(self, *args, **kwargs):  # pipeline commands are queued, then executed
        return self

    zadd = zcard = expire = zrange = zremrangebyscore

    async def execute(self, *args, **kwargs):
        raise redis.exceptions.ConnectionError("redis is down")

    async def get(self, *args, **kwargs):
        raise redis.exceptions.ConnectionError("redis is down")

    set = delete = get


async def test_signed_in_requests_survive_redis_being_down(team, monkeypatch):
    from app.security import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_redis", lambda: RedisDown())
    assert (await team.analyst.get("/api/runs")).status_code == 200
    assert (await team.analyst.get("/api/auth/me")).status_code == 200


async def test_rate_limited_actions_answer_503_with_retry_after_when_redis_is_down(team, monkeypatch):
    from app.security import ratelimit as ratelimit_api

    monkeypatch.setattr(ratelimit_api, "get_redis", lambda: RedisDown())
    r = await team.analyst.post("/api/runs", json={"question": "Why did margin fall?"})
    assert r.status_code == 503 and r.headers.get("Retry-After"), r.text


async def test_an_unreadable_saved_key_is_reported_not_a_server_error(team):
    await team.admin.put("/api/settings/llm", json=BODY)
    engine = owner_engine()
    with engine.begin() as conn:  # as if the key had been encrypted with another SECRET_KEY
        conn.execute(sa.text("SELECT set_config('app.org_id', :org, true)"), {"org": str(team.org_id)})
        conn.execute(
            sa.text("UPDATE llm_settings SET api_key_enc = 'not-a-token' WHERE org_id = :org"), {"org": team.org_id}
        )
    engine.dispose()
    view = await team.admin.get("/api/settings/llm")
    assert view.status_code == 200 and view.json()["api_key_set"] is False and "SECRET_KEY" in view.json()["key_error"]
    tested = await team.admin.post("/api/settings/llm/test")
    assert tested.status_code == 200 and tested.json()["ok"] is False and "SECRET_KEY" in tested.json()["error"]
