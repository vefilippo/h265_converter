from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Connections / secrets: optional so an unconfigured install still boots.
    # Values are configured at runtime via the setup wizard / Settings page and
    # read through get_effective(db, key, settings.X); env is only a fallback.
    # SFTP_* are prefixed to avoid collision with Windows USERNAME/HOSTNAME.
    SONARR_URL: str = ""
    SONARR_API_KEY: str = ""
    RADARR_URL: str = ""
    RADARR_API_KEY: str = ""
    SFTP_HOST: str = ""
    SFTP_USERNAME: str = ""
    SFTP_PASSWORD: str = ""
    HANDBRAKE_CLI: str = ""
    APP_PASSWORD: str = ""
    SECRET_KEY: str = ""

    # --- Defaults (overridable via .env) ---
    SFTP_PORT: int = 22
    PRESET_1080: str = "H.265 NVENC 1080p"
    PRESET_4K: str = "H.265 NVENC 2160p 4K"
    # Encoder family: auto | vcn | nvenc | qsv | cpu | custom. PRESET_1080/4K
    # above are only consulted in 'custom' mode; they are left at their historic
    # NVENC values so existing .env files keep their behaviour.
    ENCODER_FAMILY: str = "auto"
    OUTPUT_FORMAT: str = "av_mkv"
    OUTPUT_FOLDER: str = "./out/"
    WATCH_FOLDER: str = "./downloads/"
    LOCAL_FOLDER: str = "./Serie TV/"
    LOCAL_FOLDER_MOVIES: str = "./Movies/"
    RELEASE_TAG: str = "Release-OPO"
    DATABASE_URL: str = "sqlite:///transcoder.db"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8765
    WEB_DIST: str = "web/dist"

    # Docker path remap (host_root, docker_root)
    DOCKER_HOST_ROOT: str = "./out/"
    DOCKER_DOCKER_ROOT: str = "/downloads/"

    # Legacy file names (used once by migrate.py)
    EPISODE_EXCLUSION_CSV: str = "excluded_episodes.csv"
    MOVIE_EXCLUSION_CSV: str = "excluded_movies.csv"
    LAST_HISTORY_FILE: str = "last_history_timestamp.txt"

    @property
    def DOCKER_MAPPING(self) -> tuple[str, str]:
        return (self.DOCKER_HOST_ROOT, self.DOCKER_DOCKER_ROOT)


settings = Settings()


def resolve_secret_key() -> str:
    """Session-signing key. Prefer an explicit env SECRET_KEY; otherwise read a
    `secret_key` file next to the database, generating and persisting one on
    first run so sessions survive restarts. Kept out of the DB because the
    SessionMiddleware is wired up before init_db() runs."""
    import os
    import secrets
    from pathlib import Path

    if settings.SECRET_KEY:
        return settings.SECRET_KEY

    from transcoder.backup import db_path_from_url  # lazy: avoid import cycle
    db_path = db_path_from_url(settings.DATABASE_URL)
    key_file = Path(os.path.dirname(os.path.abspath(db_path)) or ".") / "secret_key"
    if key_file.exists():
        existing = key_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    generated = secrets.token_urlsafe(48)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(generated, encoding="utf-8")
    return generated
