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


class JobLogOut(BaseModel):
    log: str


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


class StatusOut(BaseModel):
    worker_alive: bool
    current_job: JobOut | None = None
    queue_length: int
    stats: list[StatRow]


class LogLine(BaseModel):
    seq: int
    ts: str
    level: str
    message: str


class LogPage(BaseModel):
    lines: list[LogLine]
    last_seq: int
