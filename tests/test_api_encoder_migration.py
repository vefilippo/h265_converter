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
from transcoder.repo import get_setting


@pytest.fixture
def booted_api(monkeypatch):
    """Like the shared `api` fixture in tests/api_conftest.py, but actually
    enters the TestClient as a context manager.

    The shared `api` fixture builds `TestClient(app)` without `with`, so the
    ASGI lifespan protocol is never invoked and `create_app`'s lifespan body
    (where the encoder-family migration and settings.seed_settings_from_env
    run) never executes -- see tests/test_api_health.py for the established
    `with TestClient(app) as client:` pattern this mirrors. These tests are
    specifically about startup-time ordering, so they need the real lifespan
    to run.
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

    app = create_app(start_worker=False)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override

    with TestClient(app) as client:
        yield client, Session


def test_fresh_install_boots_with_encoder_family_auto(booted_api):
    _client, Session = booted_api
    with Session() as db:
        assert get_setting(db, "encoder_family") == "auto"


def test_migration_runs_before_preset_seeding(booted_api):
    """The seeder writes NVENC defaults on every boot. If the backfill ran after
    it, a fresh install would be misread as a deliberate NVIDIA setup."""
    _client, Session = booted_api
    with Session() as db:
        assert get_setting(db, "handbrake_preset_1080") == "H.265 NVENC 1080p"
        assert get_setting(db, "encoder_family") == "auto"
