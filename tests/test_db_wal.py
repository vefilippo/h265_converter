from sqlalchemy import text
from transcoder.db import make_engine


def test_engine_sets_wal_and_busy_timeout(tmp_path):
    db = tmp_path / "wal.db"
    engine = make_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert int(conn.execute(text("PRAGMA busy_timeout")).scalar()) == 15000
