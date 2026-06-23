import os

from transcoder import migrate
from transcoder.config import settings
from transcoder.models import Exclusion, Setting


def test_migrate_legacy_files(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(settings.EPISODE_EXCLUSION_CSV, "w", encoding="utf-8", newline="") as f:
        f.write("Breaking Bad,3,5\n")
    with open(settings.MOVIE_EXCLUSION_CSV, "w", encoding="utf-8", newline="") as f:
        f.write("Inception\n")
    with open(settings.LAST_HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write("2025-01-01T00:00:00Z")

    result = migrate.migrate_legacy(session)

    assert result == {"episodes": 1, "movies": 1, "watermark": True}
    eps = session.query(Exclusion).filter_by(source="sonarr").all()
    assert eps[0].key == "Breaking Bad|3|5"
    mvs = session.query(Exclusion).filter_by(source="radarr").all()
    assert mvs[0].key == "Inception"
    assert session.get(Setting, "sonarr_watermark").value == "2025-01-01T00:00:00Z"
    assert not os.path.exists(settings.EPISODE_EXCLUSION_CSV)
    assert os.path.exists(settings.EPISODE_EXCLUSION_CSV + ".migrated")


def test_migrate_is_idempotent_and_safe_when_absent(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert migrate.migrate_legacy(session) == {"episodes": 0, "movies": 0, "watermark": False}


def test_migrate_overwrites_existing_migrated_file(session, tmp_path, monkeypatch):
    # A stale *.migrated already exists; os.replace must overwrite it without
    # raising FileExistsError (which os.rename would on Windows).
    monkeypatch.chdir(tmp_path)
    with open(settings.MOVIE_EXCLUSION_CSV + ".migrated", "w", encoding="utf-8") as f:
        f.write("Old Movie\n")
    with open(settings.MOVIE_EXCLUSION_CSV, "w", encoding="utf-8", newline="") as f:
        f.write("Inception\n")

    result = migrate.migrate_legacy(session)

    assert result["movies"] == 1
    assert not os.path.exists(settings.MOVIE_EXCLUSION_CSV)
    assert os.path.exists(settings.MOVIE_EXCLUSION_CSV + ".migrated")
    with open(settings.MOVIE_EXCLUSION_CSV + ".migrated", encoding="utf-8") as f:
        assert "Inception" in f.read()
