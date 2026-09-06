import datetime as dt

from pydantic import BaseModel, ConfigDict


class MediaItemOut(BaseModel):
    id: int
    source: str
    external_id: str
    title: str
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    resolution: int
    quality: str | None = None
    languages: str | None = None
    codec: str | None = None
    is_h265: bool
    eligibility: str

    model_config = ConfigDict(from_attributes=True)


class LibraryPage(BaseModel):
    total: int
    items: list[MediaItemOut]


class StatRow(BaseModel):
    source: str
    eligibility: str
    count: int


class LibraryStats(BaseModel):
    stats: list[StatRow]


class JobOut(BaseModel):
    id: int
    media_item_id: int
    state: str
    progress: int
    preset: str | None = None
    original_size: int | None = None
    output_size: int | None = None
    reduction_pct: float | None = None
    output_filename: str | None = None
    error_message: str | None = None
    title: str | None = None
    season: int | None = None
    episode: int | None = None
    phase: str | None = None
    created_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class JobPage(BaseModel):
    total: int
    items: list[JobOut]
    # Whole-table counts by state (ignores state_filter/pagination), so the UI
    # can show accurate filter badges without fetching every job.
    state_counts: dict[str, int]


class JobLogOut(BaseModel):
    log: str


class JobDeleteIn(BaseModel):
    ids: list[int]


class JobDeleteOut(BaseModel):
    deleted: int
    skipped: int


class EnqueueIn(BaseModel):
    source: str | None = None


class EnqueueOut(BaseModel):
    created: int


class ScanIn(BaseModel):
    app: str = "all"
    scope: str = "all"
    show: str | None = None
    movie: str | None = None


class ExclusionOut(BaseModel):
    id: int
    source: str
    key: str
    reason: str
    matched: bool = True  # does this exclusion correspond to a current library item?

    model_config = ConfigDict(from_attributes=True)


class ExclusionIn(BaseModel):
    source: str
    key: str
    reason: str = "manual"


class PruneOut(BaseModel):
    removed: int


class SavingsOut(BaseModel):
    bytes_saved: int        # original_bytes - output_bytes across completed jobs
    original_bytes: int     # sum of original sizes (the "before")
    output_bytes: int       # sum of transcoded sizes (the "after")
    percent_saved: float    # bytes_saved / original_bytes * 100 (0 if no data)
    files_done: int         # number of completed (state="done") jobs


class StatusOut(BaseModel):
    worker_alive: bool
    current_job: JobOut | None = None
    queue_length: int
    stats: list[StatRow]
    savings: SavingsOut


class LogLine(BaseModel):
    seq: int
    ts: str
    level: str
    message: str


class LogPage(BaseModel):
    lines: list[LogLine]
    last_seq: int


class SettingsOut(BaseModel):
    scheduler_cron: str | None = None
    scheduler_run_at_startup: str = "false"
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    radarr_url: str = ""
    radarr_api_key: str = ""
    sftp_host: str = ""
    sftp_port: str = "22"
    sftp_username: str = ""
    sftp_password: str = ""
    handbrake_cli: str = ""
    handbrake_preset_1080: str = "H.265 NVENC 1080p"
    handbrake_preset_4k: str = "H.265 NVENC 2160p 4K"
    encoder_family: str = "auto"
    encoder_fallback_cpu: str = "true"
    scheduler_next_run: str | None = None
    webhook_username: str = ""
    webhook_password_set: bool = False


class SettingsUpdate(BaseModel):
    scheduler_cron: str | None = None
    scheduler_run_at_startup: str | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
    radarr_url: str | None = None
    radarr_api_key: str | None = None
    sftp_host: str | None = None
    sftp_port: str | None = None
    sftp_username: str | None = None
    sftp_password: str | None = None
    handbrake_cli: str | None = None
    handbrake_preset_1080: str | None = None
    handbrake_preset_4k: str | None = None
    encoder_family: str | None = None
    encoder_fallback_cpu: str | None = None
    current_password: str | None = None
    new_password: str | None = None
    webhook_username: str | None = None
    webhook_password: str | None = None
