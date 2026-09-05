"""A restored backup must not carry its old host's encoder capability cache.

`make_backup` snapshots the whole DB, so `encoder_capabilities` travels with it.
Restoring an NVIDIA backup onto an AMD box would otherwise leave an
authoritative-looking `{"available": ["nvenc","cpu"]}` blob behind: 'auto' would
resolve to nvenc and every job would fail in HandBrake, and — worse — an
explicit `encoder_family=nvenc` would NOT trigger the CPU fallback, because
nvenc *is* in the stale set. Restore-onto-new-hardware is the documented purpose
of the feature, so the cache must be blanked and re-probed lazily.
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401
import transcoder.api.app as app_module
from transcoder import encoders
from transcoder.api.app import create_app
from transcoder.repo import get_setting, set_setting

STALE_BLOB = json.dumps({
    "available": ["cpu", "nvenc"],
    "detected_at": "2026-01-01T00:00:00+00:00",
})


def _boot(monkeypatch, *, restored: bool):
    """Boot the real lifespan against an in-memory DB seeded with a stale cache."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with Session() as db:
        set_setting(db, encoders.CAPABILITIES_KEY, STALE_BLOB)
        db.commit()

    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "SessionLocal", Session)
    import transcoder.db as db_module
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "reconcile_stale_jobs", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "init_logging", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "apply_pending_restore", lambda *a, **k: restored)
    import transcoder.api.auth as auth_module
    monkeypatch.setattr(auth_module, "SessionLocal", Session)

    app = create_app(start_worker=False)
    with TestClient(app):
        pass
    return Session


def test_restored_db_comes_up_with_unknown_capabilities(monkeypatch):
    Session = _boot(monkeypatch, restored=True)
    with Session() as db:
        assert encoders.load_capabilities(db)[0] == set()
        assert not get_setting(db, encoders.CAPABILITIES_KEY)


def test_ordinary_boot_keeps_the_cached_capabilities(monkeypatch):
    """No restore, no invalidation: the lazy probe stays a one-off, not a
    subprocess call on every server start."""
    Session = _boot(monkeypatch, restored=False)
    with Session() as db:
        assert encoders.load_capabilities(db)[0] == {"cpu", "nvenc"}
