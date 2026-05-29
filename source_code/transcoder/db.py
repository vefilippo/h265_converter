from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from transcoder.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    return create_engine(
        url or settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(eng=engine) -> None:
    import transcoder.models  # noqa: F401  (register tables)
    Base.metadata.create_all(eng)
