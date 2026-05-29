import os

# Required settings must exist before transcoder.config is imported.
os.environ.setdefault("SONARR_URL", "http://sonarr.test")
os.environ.setdefault("SONARR_API_KEY", "test-sonarr-key")
os.environ.setdefault("RADARR_URL", "http://radarr.test")
os.environ.setdefault("RADARR_API_KEY", "test-radarr-key")
os.environ.setdefault("SFTP_HOST", "127.0.0.1")
os.environ.setdefault("SFTP_USERNAME", "tester")
os.environ.setdefault("SFTP_PASSWORD", "secret")
os.environ.setdefault("HANDBRAKE_CLI", "HandBrakeCLI")
os.environ.setdefault("APP_PASSWORD", "test-pass")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session():
    # Imported lazily so pytest can collect tests (e.g. test_config) before the
    # db/models modules exist in earlier tasks.
    from transcoder.db import Base
    import transcoder.models  # noqa: F401  (registers tables on Base)

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    # Mirror production SessionLocal (db.py): autoflush=False so tests exercise
    # the same flush semantics as the real app.
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


from tests.api_conftest import api  # noqa: E402,F401  (re-export API fixture)
