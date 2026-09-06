"""The transcode worker must not start before the encoder-family migration.

`controller.start()` spawns a thread that immediately looks for queued jobs (no
initial sleep), and `reconcile_stale_jobs` has just re-queued anything orphaned
in 'running'. If the worker wins the race on the first boot after an upgrade,
`resolve_for_job` finds no `encoder_family` row, defaults to 'auto', and ignores
the hand-tuned presets the migration exists to preserve — for one whole job.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401
import transcoder.api.app as app_module
from transcoder import encoders
from transcoder.api import state


def test_worker_starts_after_the_encoder_family_migration(monkeypatch):
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
    import transcoder.db as db_module
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "init_logging", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "apply_pending_restore", lambda *a, **k: False)
    import transcoder.api.auth as auth_module
    monkeypatch.setattr(auth_module, "SessionLocal", Session)

    calls: list[str] = []
    monkeypatch.setattr(app_module, "reconcile_stale_jobs",
                        lambda *a, **k: calls.append("reconcile"))
    monkeypatch.setattr(encoders, "migrate_encoder_family",
                        lambda db: calls.append("migrate") or None)
    # Never spawn a real worker thread in the suite; just record the ordering.
    monkeypatch.setattr(state.controller, "start", lambda *a, **k: calls.append("worker"))
    monkeypatch.setattr(state.controller, "shutdown", lambda *a, **k: None)

    app = app_module.create_app(start_worker=True)
    with TestClient(app):
        pass

    assert calls == ["reconcile", "migrate", "worker"]
