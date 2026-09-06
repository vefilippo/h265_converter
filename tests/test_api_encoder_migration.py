import pytest

from tests.api_conftest import build_booted_client
from transcoder.repo import get_setting


@pytest.fixture
def booted_api(monkeypatch):
    """Like the shared `api` fixture in tests/api_conftest.py, but actually
    enters the TestClient as a context manager.

    The shared `api` fixture builds `TestClient(app)` without `with`, so the
    ASGI lifespan protocol is never invoked and `create_app`'s lifespan body
    (where the encoder-family migration and settings.seed_settings_from_env
    run) never executes -- see tests/test_api_health.py for the established
    `with TestClient(app) as client:` pattern this mirrors. These tests are
    specifically about startup-time ordering, so they need the real lifespan
    to run.
    """
    from transcoder.config import settings as cfg

    # Self-contained regardless of a developer's environment: pin the preset
    # default this test relies on rather than depending on cfg's default.
    monkeypatch.setattr(cfg, "PRESET_1080", "H.265 NVENC 1080p")
    # A family other than "auto" so the assertion below can tell "the config
    # value flowed through migration" apart from "happens to match the schema
    # literal" -- both would be "auto" otherwise, and the test couldn't
    # discriminate between the two.
    monkeypatch.setattr(cfg, "ENCODER_FAMILY", "cpu")

    client, Session = build_booted_client(monkeypatch)
    with client as c:
        yield c, Session


def test_migration_runs_before_preset_seeding(booted_api):
    """The seeder writes NVENC defaults on every boot. If the backfill ran after
    it, a fresh install would be misread as a deliberate NVIDIA setup."""
    _client, Session = booted_api
    with Session() as db:
        assert get_setting(db, "handbrake_preset_1080") == "H.265 NVENC 1080p"
        assert get_setting(db, "encoder_family") == "cpu"
