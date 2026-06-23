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
