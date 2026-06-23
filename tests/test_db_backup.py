def test_backup_db_creates_bak_file(tmp_path):
    from transcoder.db import backup_db
    db = tmp_path / "transcoder.db"
    db.write_bytes(b"SQLite data")
    backup_db(db)
    bak = tmp_path / "transcoder.db.bak"
    assert bak.exists()
    assert bak.read_bytes() == b"SQLite data"


def test_backup_db_no_error_when_file_missing(tmp_path):
    from transcoder.db import backup_db
    db = tmp_path / "transcoder.db"
    backup_db(db)  # must not raise


def test_backup_db_overwrites_previous_bak(tmp_path):
    from transcoder.db import backup_db
    db = tmp_path / "transcoder.db"
    bak = tmp_path / "transcoder.db.bak"
    bak.write_bytes(b"old backup")
    db.write_bytes(b"new data")
    backup_db(db)
    assert bak.read_bytes() == b"new data"
