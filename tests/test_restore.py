from pathlib import Path
from transcoder import restore


def test_apply_noop_when_no_marker(tmp_path):
    assert restore.apply_pending_restore(
        str(tmp_path), str(tmp_path / "transcoder.db"), str(tmp_path / ".env")
    ) is False


def test_stage_then_apply_swaps_db_and_env(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    db.write_bytes(b"OLD-DB"); env.write_text("OLD=1\n", encoding="utf-8")

    restore.stage_restore(b"NEW-DB", "NEW=2\n", str(tmp_path))
    # marker + staged files exist
    assert (tmp_path / restore.PENDING_DIR / restore.MARKER).exists()

    applied = restore.apply_pending_restore(str(tmp_path), str(db), str(env))
    assert applied is True
    assert db.read_bytes() == b"NEW-DB"
    assert env.read_text(encoding="utf-8") == "NEW=2\n"
    # staging cleaned up so it doesn't re-apply next boot
    assert not (tmp_path / restore.PENDING_DIR).exists()
    # second call is a no-op
    assert restore.apply_pending_restore(str(tmp_path), str(db), str(env)) is False


def test_empty_env_text_skips_env_write(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    db.write_bytes(b"OLD"); env.write_text("KEEP=1\n", encoding="utf-8")
    restore.stage_restore(b"NEW", "", str(tmp_path))
    restore.apply_pending_restore(str(tmp_path), str(db), str(env))
    assert db.read_bytes() == b"NEW"
    assert env.read_text(encoding="utf-8") == "KEEP=1\n"  # unchanged when backup had no env


def test_apply_noop_when_pending_dir_present_but_no_marker(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    db.write_bytes(b"OLD"); env.write_text("OLD=1\n", encoding="utf-8")
    # Pending dir with staged files but NO marker (a half-staged crash).
    pend = tmp_path / restore.PENDING_DIR
    pend.mkdir()
    (pend / "transcoder.db").write_bytes(b"NEW")
    (pend / "env.txt").write_text("NEW=2\n", encoding="utf-8")
    assert restore.apply_pending_restore(str(tmp_path), str(db), str(env)) is False
    assert db.read_bytes() == b"OLD"  # nothing applied without the marker
    assert env.read_text(encoding="utf-8") == "OLD=1\n"
