from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from transcoder.config import settings


class Base(DeclarativeBase):
    pass


def _enable_sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
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
