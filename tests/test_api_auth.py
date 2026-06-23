import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from transcoder.api.auth import router as auth_router, require_auth


@pytest.fixture
def client(monkeypatch):
    # auth.login reads SessionLocal directly; without isolation it hits the real
    # transcoder.db (and its app_password_hash), so the env-password fallback
    # never runs. Point it at an empty in-memory DB so login uses APP_PASSWORD.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
    from transcoder.db import Base
    import transcoder.models  # noqa: F401
    import transcoder.api.auth as auth_module

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(auth_module, "SessionLocal",
                        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.include_router(auth_router)

    @app.get("/api/secret", dependencies=[Depends(require_auth)])
    def secret():
        return {"ok": True}

    return TestClient(app)


def test_me_unauthed(client):
    body = client.get("/api/me").json()
    assert body["authed"] is False


def test_protected_requires_auth(client):
    assert client.get("/api/secret").status_code == 401


def test_login_wrong_password(client):
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401


def test_login_then_access_then_logout(client):
    assert client.post("/api/login", json={"password": "test-pass"}).json() == {"ok": True}
    assert client.get("/api/me").json()["authed"] is True
    assert client.get("/api/secret").status_code == 200
    assert client.post("/api/logout").json() == {"ok": True}
    assert client.get("/api/secret").status_code == 401
