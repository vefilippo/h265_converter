from dataclasses import dataclass

# Copy this file to `config.py` and fill in your own values.
# `config.py` is gitignored so real credentials never enter version control.
# (Cycle 1 will replace this with a `.env` file loaded via pydantic-settings.)

@dataclass(frozen=True)
class Settings:
    # Sonarr API Configuration
    SONARR_URL = "http://your-sonarr-host:8989"
    SONARR_API_KEY = "YOUR_SONARR_API_KEY"

    # Radarr API Configuration
    RADARR_URL = "http://your-radarr-host:7878"
    RADARR_API_KEY = "YOUR_RADARR_API_KEY"

    # If Sonarr/Radarr runs in Docker and sees a *different* root path, set
    DOCKER_MAPPING = ("./out/", "/downloads/")
    WATCH_FOLDER = './downloads/'

    # HandBrake CLI Configuration
    HANDBRAKE_CLI = "C:\\path\\to\\HandBrakeCLI.exe"
    PRESET_1080 = "H.265 NVENC 1080p"
    PRESET_4K = "H.265 NVENC 2160p 4K"
    OUTPUT_FORMAT = "av_mkv"
    OUTPUT_FOLDER = "./out/"
    EPISODE_EXCLUSION_CSV = "excluded_episodes.csv"
    MOVIE_EXCLUSION_CSV = "excluded_movies.csv"
    LOCAL_FOLDER = "./Serie TV/"
    LOCAL_FOLDER_MOVIES = "./Movies/"

    # SFTP Configuration
    HOSTNAME = "192.168.x.x"
    PORT = 22
    USERNAME = "YOUR_SFTP_USER"
    PASSWORD = "YOUR_SFTP_PASSWORD"

    H265_KEYWORDS = ["h265", "hevc", "x265", "h.265"]
    LAST_HISTORY_FILE = "last_history_timestamp.txt"
    RELEASE_TAG = "Release-OPO"

settings = Settings()
