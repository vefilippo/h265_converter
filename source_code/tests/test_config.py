def test_settings_loads_required_from_env():
    from transcoder.config import settings
    assert settings.SONARR_URL == "http://sonarr.test"
    assert settings.SONARR_API_KEY == "test-sonarr-key"


def test_settings_has_defaults():
    from transcoder.config import settings
    assert settings.PRESET_1080 == "H.265 NVENC 1080p"
    assert settings.DATABASE_URL.startswith("sqlite")
    assert settings.SFTP_PORT == 22
