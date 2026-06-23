import sqlite3
import zipfile
import io
import pytest
from transcoder import backup


def _make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    con.commit(); con.close()


def test_db_path_from_url():
    assert backup.db_path_from_url("sqlite:///transcoder.db") == "transcoder.db"
    assert backup.db_path_from_url("sqlite:////abs/x.db") == "/abs/x.db"


def test_snapshot_preserves_rows(tmp_path):
    src = tmp_path / "a.db"; dst = tmp_path / "b.db"
    _make_db(str(src))
    backup.snapshot_db(str(src), str(dst))
    con = sqlite3.connect(str(dst))
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    con.close()


def test_make_and_read_backup_roundtrip(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    _make_db(str(db)); env.write_text("APP_PASSWORD=s3cret\n", encoding="utf-8")
    blob = backup.make_backup(str(db), str(env), "pw", app_version="9.9.9",
                              created_at="2026-06-23T00:00:00Z")
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert set(names) == {"transcoder.db", "env.enc", "manifest.json"}
    db_bytes, env_text, manifest = backup.read_backup(blob, "pw")
    assert env_text == "APP_PASSWORD=s3cret\n"
    assert manifest["app_version"] == "9.9.9"
    assert db_bytes[:16] == b"SQLite format 3\x00"


def test_read_backup_wrong_passphrase_raises(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    _make_db(str(db)); env.write_text("X=1\n", encoding="utf-8")
    blob = backup.make_backup(str(db), str(env), "right", created_at="now")
    with pytest.raises(Exception):
        backup.read_backup(blob, "wrong")
