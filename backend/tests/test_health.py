async def test_healthz_reports_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_ok_when_database_and_redis_answer(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


async def test_readyz_names_the_failing_dependency(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://finops_app:wrong@localhost:1/none")
    get_settings.cache_clear()
    try:
        r = await client.get("/readyz")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "failing": ["database"]}


async def test_every_response_carries_a_request_id(client):
    r = await client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    assert len((await client.get("/healthz")).headers["X-Request-ID"]) >= 16
