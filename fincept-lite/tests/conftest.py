import os
import sys
from pathlib import Path

os.environ.setdefault("FINCEPT_DATA_MODE", "sim")
os.environ.setdefault("FINCEPT_DB", ":memory:")
os.environ.setdefault("FINCEPT_ALLOWED_HOSTS", "testserver")
os.environ.setdefault("FINCEPT_AI", "offline")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import itertools  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

_n = itertools.count(1)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user(client):
    """Usuario nuevo verificado: devuelve dict con email, password, api_key, session_token, headers."""
    i = next(_n)
    email, pw = f"user{i}@example.com", "secret-pass-1"
    r = client.post("/user/register", json={"username": f"user{i}", "email": email, "password": pw,
                                            "phone": "600000000", "country_code": "+34"}).json()
    assert r["success"], r
    v = client.post("/user/verify-otp", json={"email": email, "otp": r["data"]["dev_otp"]}).json()
    assert v["success"], v
    d = v["data"]
    return {"email": email, "password": pw, "api_key": d["api_key"], "session_token": d["session_token"],
            "id": d["user"]["id"],
            "headers": {"X-API-Key": d["api_key"], "X-Session-Token": d["session_token"]}}
