from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from transcoder.config import settings


class Base(DeclarativeBase):
    pass


def _enable_sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    # Wait (rather than erroring with "database is locked") when another writer
    # holds the lock briefly. Writers serialize in SQLite; discovery commits in
    # batches so any wait stays short in practice.
    cur.execute("PRAGMA busy_timeout=15000")
    cur.close()


def make_engine(url: str | None = None):
    engine = create_engine(
        url or settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _enable_sqlite_pragmas)
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(eng=engine) -> None:
    import transcoder.models  # noqa: F401  (register tables)
    Base.metadata.create_all(eng)


def ensure_job_columns(engine=None):
    """Idempotently add the job.phase / job.log columns to an existing DB and
    copy any legacy log_excerpt content into log. No-op when already present or
    when the job table doesn't exist yet (fresh DBs get the columns via
    create_all)."""
    eng = engine or make_engine()
    with eng.begin() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "job" not in tables:
            return
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(job)"))}
        if "phase" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN phase VARCHAR(16)"))
        if "log" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN log TEXT"))
            if "log_excerpt" in cols:
                conn.execute(text(
                    "UPDATE job SET log = log_excerpt "
                    "WHERE log IS NULL AND log_excerpt IS NOT NULL"))
