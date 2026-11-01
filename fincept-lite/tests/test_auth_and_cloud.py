def test_register_validation_returns_pydantic_422(client):
    r = client.post("/user/register", json={"username": "x", "email": "not-an-email", "password": "short"})
    assert r.status_code == 422
    fields = {e["loc"][-1] for e in r.json()["detail"]}
    assert {"username", "email", "password"} <= fields


def test_duplicate_email_is_business_error_with_200(client, user):
    r = client.post("/user/register", json={"username": "otro", "email": user["email"], "password": "12345678x"})
    assert r.status_code == 200
    assert r.json() == {"success": False, "message": "An account with this email already exists."}


def test_wrong_otp_counts_attempts(client):
    r = client.post("/user/register", json={"username": "otpuser", "email": "otp@example.com", "password": "12345678x"})
    good = r.json()["data"]["dev_otp"]
    bad = "000000" if good != "000000" else "111111"
    m = client.post("/user/verify-otp", json={"email": "otp@example.com", "otp": bad}).json()
    assert m["success"] is False and "2 attempt(s) remaining" in m["message"]
    ok = client.post("/user/verify-otp", json={"email": "otp@example.com", "otp": good}).json()
    assert ok["success"] and ok["data"]["api_key"].startswith("fk_user_")


def test_login_lockout_after_three_failures(client, user):
    msgs = [client.post("/user/login", json={"email": user["email"], "password": "wrong-pass"}).json()["message"]
            for _ in range(3)]
    assert "2 attempt(s) remaining" in msgs[0]
    assert "1 attempt(s) remaining" in msgs[1]
    assert "try again in 2 minutes" in msgs[2]
    locked = client.post("/user/login", json={"email": user["email"], "password": user["password"]}).json()
    assert locked["success"] is False and "Too many failed attempts" in locked["message"]


def test_single_active_session_and_force_login(client, user):
    first = client.post("/user/login", json={"email": user["email"], "password": user["password"]}).json()
    assert first["data"]["active_session"] is True  # la sesión de verify-otp sigue activa
    forced = client.post("/user/login", json={"email": user["email"], "password": user["password"],
                                              "force_login": True}).json()["data"]
    new_headers = {"X-API-Key": forced["api_key"], "X-Session-Token": forced["session_token"]}
    # el dispositivo anterior recibe 401 → SessionGuard cerraría sesión
    assert client.get("/user/session-pulse", headers=user["headers"]).status_code == 401
    assert client.get("/user/session-pulse", headers=new_headers).json()["data"]["alive"] is True


def test_profile_shape_matches_terminal_userprofile(client, user):
    p = client.get("/user/profile", headers=user["headers"]).json()["data"]
    for k in ("id", "username", "email", "account_type", "credit_balance", "is_verified", "mfa_enabled",
              "rate_limit"):
        assert k in p
    assert p["account_type"] == "free" and p["credit_balance"] == 350
    assert set(p["rate_limit"]) == {"limit", "remaining", "reset_at", "window_seconds", "concurrent_limit"}


def test_missing_api_key_is_401(client):
    assert client.get("/user/profile").status_code == 401


def test_v1_envelope_and_bearer_auth(client, user):
    h = {"Authorization": f"Bearer {user['api_key']}"}
    r = client.get("/v1/watchlists", headers=h).json()
    assert r["success"] is True and r["data"][0]["name"] == "Principal"
    created = client.post("/v1/watchlists", headers=h, json={"name": "Bancos", "symbols": ["jpm", "san.mc"]}).json()
    assert created["data"]["symbols"] == ["JPM", "SAN.MC"]
    dup = client.post("/v1/watchlists", headers=h, json={"name": "Bancos", "symbols": []})
    assert dup.status_code == 409 and dup.json()["error"] == "conflict" and dup.json()["hint"]
    wid = created["data"]["id"]
    upd = client.put(f"/v1/watchlists/{wid}", headers=h, json={"name": "Bancos", "symbols": ["BBVA.MC"]}).json()
    assert upd["data"]["symbols"] == ["BBVA.MC"]
    assert client.delete(f"/v1/watchlists/{wid}", headers=h).json()["success"]
    assert client.delete(f"/v1/watchlists/{wid}", headers=h).status_code == 404


def test_logout_invalidates_session(client, user):
    assert client.post("/user/logout", headers=user["headers"]).json()["success"]
    assert client.get("/user/session-pulse", headers=user["headers"]).status_code == 401
