import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401
import transcoder.cli as cli_module
from transcoder.repo import get_setting, set_setting


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _run_cli_queue(monkeypatch, Session):
    """Drive transcoder.cli.main() down the 'queue' command path -- it opens a
    session, runs the encoder-family backfill + legacy migration, then lists
    jobs and returns before touching Sonarr/Radarr, so it never needs real
    clients or network access."""
    monkeypatch.setattr(cli_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(cli_module, "init_logging", lambda *a, **k: None)
    monkeypatch.setattr(cli_module, "SessionLocal", Session)
    monkeypatch.setattr(cli_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["cli.py", "queue"])
    cli_module.main()


def test_cli_backfills_encoder_family_on_fresh_db(monkeypatch):
    Session = _session_factory()

    _run_cli_queue(monkeypatch, Session)

    with Session() as db:
        assert get_setting(db, "encoder_family") == "auto"


def test_cli_infers_family_from_hand_tuned_presets(monkeypatch):
    """Before this fix, a CLI-only user's hand-tuned NVENC presets were never
    migrated to encoder_family, so resolve_for_job() defaulted them to 'auto'
    and silently ignored the hand-tuned presets on every CLI run."""
    Session = _session_factory()
    with Session() as db:
        set_setting(db, "handbrake_preset_1080", "H.265 NVENC 1080p")
        set_setting(db, "handbrake_preset_4k", "H.265 NVENC 2160p 4K")
        db.commit()

    _run_cli_queue(monkeypatch, Session)

    with Session() as db:
        assert get_setting(db, "encoder_family") == "nvenc"
