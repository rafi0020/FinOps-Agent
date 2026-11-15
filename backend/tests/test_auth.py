"""Sign-up, sign-in, sessions and CSRF, exercised through the HTTP API."""

from tests.conftest import PASSWORD


async def test_signup_creates_an_org_with_its_first_admin(team):
    r = await team.admin.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
    assert r.json()["user"]["email"] == team.emails["admin"]


async def test_wrong_password_and_unknown_account_get_the_same_answer(client, team):
    wrong = await client.post("/api/auth/login", json={"email": team.emails["viewer"], "password": "nope-12345"})
    unknown = await client.post("/api/auth/login", json={"email": "nobody@example.test", "password": "nope-12345"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Incorrect e-mail or password."}


async def test_sixth_failed_login_in_a_minute_is_refused(client):
    body = {"email": "locked-out@example.test", "password": "wrong-password-1"}
    for _ in range(5):
        assert (await client.post("/api/auth/login", json=body)).status_code == 401
    r = await client.post("/api/auth/login", json=body)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


async def test_session_cookie_is_httponly_and_samesite(client, team):
    r = await client.post("/api/auth/login", json={"email": team.emails["viewer"], "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "finops_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


async def test_state_changing_request_without_csrf_token_is_refused(team):
    del team.analyst.headers["X-CSRF-Token"]
    r = await team.analyst.post("/api/auth/logout")
    assert r.status_code == 403
    assert (await team.analyst.get("/api/auth/me")).status_code == 200  # still signed in


async def test_logout_ends_the_session_on_the_server(team):
    cookie = team.viewer.cookies["finops_session"]
    assert (await team.viewer.post("/api/auth/logout")).status_code == 204
    team.viewer.cookies.set("finops_session", cookie)  # replay the old cookie
    assert (await team.viewer.get("/api/auth/me")).status_code == 401


async def test_no_cookie_means_not_signed_in(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/users")).status_code == 401


async def test_weak_password_is_rejected_with_the_reason(client):
    base = {"email": "weak@example.test", "name": "W", "org_name": "Weak Org"}
    assert (await client.post("/api/auth/signup", json=base | {"password": "short1"})).status_code == 422
    r = await client.post("/api/auth/signup", json=base | {"password": "onlyletterslong"})
    assert r.status_code == 422 and "letter and a number" in r.json()["detail"]


async def test_duplicate_email_cannot_sign_up(client, team):
    r = await client.post(
        "/api/auth/signup",
        json={
            "email": team.emails["admin"].upper(),
            "password": PASSWORD,
            "name": "X",
            "org_name": "Dup Org",
        },
    )
    assert r.status_code == 409


async def test_changing_password_signs_out_other_sessions(team):
    second = await team.login(team.emails["analyst"])
    r = await team.analyst.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "Brand-New-Pass-7"}
    )
    assert r.status_code == 204
    assert (await team.analyst.get("/api/auth/me")).status_code == 200
    assert (await second.get("/api/auth/me")).status_code == 401
    assert (await team.login(team.emails["analyst"], "Brand-New-Pass-7")) is not None
