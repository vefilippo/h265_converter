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

# Isolate the DB from the developer's real transcoder.db. The old default
# (sqlite:///transcoder.db, cwd-relative) only worked because pytest ran from
# source_code/ next to the populated DB; from the repo root that resolves to an
# empty file and import-time settings reads (api.state) hit "no such table".
# Point at a throwaway file DB and create the schema so those reads find an
# (empty) setting table and fall back to the test env defaults above.
import tempfile

_test_db = os.path.join(tempfile.mkdtemp(prefix="h265_test_"), "test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_test_db.replace(os.sep, '/')}")

from transcoder.db import init_db  # noqa: E402  (after DATABASE_URL is set)

init_db()

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


@pytest.fixture(autouse=True)
def _no_encoder_probe(monkeypatch):
    """Keep tests hermetic: never shell out to a real HandBrakeCLI.

    Returns two empty sets, i.e. "capabilities unknown". Tests that care about
    specific hardware seed the cache with encoders.store_capabilities() or
    monkeypatch encoders.probe themselves, which overrides this.
    """
    try:
        from transcoder import encoders
    except ImportError:
        return  # module does not exist yet in earlier tasks
    monkeypatch.setattr(encoders, "probe", lambda *a, **k: (set(), set()))
