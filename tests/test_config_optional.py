"""A fresh install has no .env (gitignored), so Settings must load with the
connection/credential fields defaulting to "" instead of raising
ValidationError and crashing the app at import."""

REQUIRED_NOW_OPTIONAL = [
    "SONARR_URL", "SONARR_API_KEY", "RADARR_URL", "RADARR_API_KEY",
    "SFTP_HOST", "SFTP_USERNAME", "SFTP_PASSWORD", "HANDBRAKE_CLI",
    "APP_PASSWORD", "SECRET_KEY",
]


def test_settings_loads_with_no_env(monkeypatch):
    # tests/conftest.py sets these in os.environ; remove them so we exercise the
    # true empty-install path.
    for key in REQUIRED_NOW_OPTIONAL:
        monkeypatch.delenv(key, raising=False)
    from transcoder.config import Settings
    s = Settings(_env_file=None)
    for key in REQUIRED_NOW_OPTIONAL:
        assert getattr(s, key) == "", key
