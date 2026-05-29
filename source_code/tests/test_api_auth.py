import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from transcoder.api.auth import router as auth_router, require_auth


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.include_router(auth_router)

    @app.get("/api/secret", dependencies=[Depends(require_auth)])
    def secret():
        return {"ok": True}

    return TestClient(app)


def test_me_unauthed(client):
    assert client.get("/api/me").json() == {"authed": False}


def test_protected_requires_auth(client):
    assert client.get("/api/secret").status_code == 401


def test_login_wrong_password(client):
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401


def test_login_then_access_then_logout(client):
    assert client.post("/api/login", json={"password": "test-pass"}).json() == {"ok": True}
    assert client.get("/api/me").json() == {"authed": True}
    assert client.get("/api/secret").status_code == 200
    assert client.post("/api/logout").json() == {"ok": True}
    assert client.get("/api/secret").status_code == 401
