def test_settings_loads_required_from_env():
    from transcoder.config import settings
    assert settings.SONARR_URL == "http://sonarr.test"
    assert settings.SONARR_API_KEY == "test-sonarr-key"


def test_settings_has_defaults():
    from transcoder.config import settings
    assert settings.PRESET_1080 == "H.265 NVENC 1080p"
    assert settings.DATABASE_URL.startswith("sqlite")
    assert settings.SFTP_PORT == 22


def test_settings_api_defaults():
    from transcoder.config import settings
    assert settings.API_PORT == 8765
    assert settings.API_HOST == "0.0.0.0"


def test_settings_web_auth_defaults():
    from transcoder.config import settings
    assert settings.WEB_DIST == "web/dist"
    assert settings.APP_PASSWORD  # provided by conftest env
    assert settings.SECRET_KEY


def test_encoder_family_defaults_to_auto():
    from transcoder.config import settings
    assert settings.ENCODER_FAMILY == "auto"
