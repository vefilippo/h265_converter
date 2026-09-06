import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401
import transcoder.api.app as app_module
from transcoder.api.app import create_app
from transcoder.api.deps import get_session


def _yield(Session):
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def api(monkeypatch):
    """TestClient with an isolated in-memory DB; no worker, no migration.

    Yields (client, Session) so tests can seed data directly via Session().
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Neutralize lifespan side-effects that touch the real DB/.env.
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "SessionLocal", Session)
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "reconcile_stale_jobs", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "init_logging", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "apply_pending_restore", lambda *a, **k: False)
    # auth.py imports SessionLocal directly, so patching app_module's reference
    # above isn't enough — without this the login endpoint reads the real
    # transcoder.db (and its app_password_hash), breaking the fixture's
    # default login on any machine that has a real DB. Point it at the
    # in-memory DB so login falls back to the env APP_PASSWORD ("test-pass").
    import transcoder.api.auth as auth_module
    monkeypatch.setattr(auth_module, "SessionLocal", Session)

    app = create_app(start_worker=False)

    def _override():
        yield from _yield(Session)

    app.dependency_overrides[get_session] = _override

    client = TestClient(app)
    client.post("/api/login", json={"password": "test-pass"})  # authenticate by default
    yield client, Session
    client.close()


def build_booted_client(monkeypatch, *, start_worker=False):
    """An app booted through the REAL ASGI lifespan, on a fresh in-memory DB.

    Distinct from the shared `api` fixture above, which deliberately does not
    enter the TestClient context manager (see that fixture's neighbouring
    comments). Startup-ordering tests need the lifespan to actually run --
    that's where the encoder-family migration and settings.seed_settings_from_env
    run -- so this boots through `with TestClient(app) as client:` instead.

    Returns (client_context_manager, Session); the caller is responsible for
    entering the context manager (typically inside its own fixture).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "SessionLocal", Session)
    # app.py's lifespan re-imports SessionLocal fresh from transcoder.db right
    # before the seeding/migration block (`from transcoder.db import
    # SessionLocal as _SL`), which bypasses the patch on app_module above --
    # that name binding lives in transcoder.db's own namespace.
    import transcoder.db as db_module
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "reconcile_stale_jobs", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "init_logging", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "apply_pending_restore", lambda *a, **k: False)
    import transcoder.api.auth as auth_module
    monkeypatch.setattr(auth_module, "SessionLocal", Session)

    app = create_app(start_worker=start_worker)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override

    return TestClient(app), Session
