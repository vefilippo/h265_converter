import os

# Required settings must exist before transcoder.config is imported.
os.environ.setdefault("SONARR_URL", "http://sonarr.test")
os.environ.setdefault("SONARR_API_KEY", "test-sonarr-key")
os.environ.setdefault("RADARR_URL", "http://radarr.test")
os.environ.setdefault("RADARR_API_KEY", "test-radarr-key")
os.environ.setdefault("HOSTNAME", "127.0.0.1")
os.environ.setdefault("USERNAME", "tester")
os.environ.setdefault("PASSWORD", "secret")
os.environ.setdefault("HANDBRAKE_CLI", "HandBrakeCLI")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401  (registers tables on Base)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
