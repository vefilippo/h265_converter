# H.265 Converter Service — Cycle 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the H.265 transcoder engine on a persistent SQLite job/state foundation with secrets in `.env`, real logging, and captured transcode progress — preserving today's behavior exactly, runnable/testable from the CLI with no web layer.

**Architecture:** Split the two monolithic `handle_*` functions into composable `discovery → queue → worker` units that take an injected SQLAlchemy `Session` (so they're unit-testable with mocks). State lives in SQLite (`media_item`, `job`, `exclusion`, `setting`) replacing the CSV/timestamp files, with a one-time legacy migration. A single serial worker processes one job at a time.

**Tech Stack:** Python 3.10, SQLAlchemy 2.0, pydantic-settings, pytest. Existing: requests, paramiko, tqdm, HandBrake CLI.

**Spec:** `docs/superpowers/specs/2026-05-29-h265-service-foundation-design.md`

**Working directory for all commands:** `source_code/` (the package root). Tests live in `source_code/tests/`.

---

## File Structure

**Create:**
- `source_code/tests/conftest.py` — pytest fixtures (in-memory DB session, env defaults)
- `source_code/tests/test_*.py` — one per unit
- `source_code/pytest.ini` — pytest config
- `source_code/.env.example` — committed template
- `source_code/transcoder/db.py` — engine/session/Base/init_db
- `source_code/transcoder/models.py` — ORM models + key helpers
- `source_code/transcoder/repo.py` — small shared data-access helpers
- `source_code/transcoder/migrate.py` — legacy CSV/timestamp → DB
- `source_code/transcoder/engine/__init__.py`
- `source_code/transcoder/engine/eligibility.py` — pure eligibility rule
- `source_code/transcoder/engine/discovery.py` — scan Sonarr/Radarr → media_items
- `source_code/transcoder/engine/queue.py` — eligible items → jobs
- `source_code/transcoder/engine/worker.py` — drain queue, one job at a time

**Modify:**
- `source_code/requirements.txt` — add deps
- `source_code/transcoder/config.py` — pydantic-settings from `.env` (kept local, gitignored)
- `source_code/transcoder/config.example.py` — mirror new shape
- `source_code/transcoder/convert.py` — extract progress parser + `progress_cb`
- `source_code/transcoder/logging_setup.py` — real leveled logging (drop print monkeypatch)
- `source_code/transcoder/radarr_client.py` — include ids in `filter_non_h265_movies`
- `source_code/transcoder/cli.py` — thin `scan`/`run`/`queue` backed by the engine

---

## Task 1: Dependencies & test scaffolding

**Files:**
- Modify: `source_code/requirements.txt`
- Create: `source_code/pytest.ini`
- Create: `source_code/tests/conftest.py`

- [ ] **Step 1: Add dependencies**

Set `source_code/requirements.txt` to:

```
requests
paramiko
tqdm
SQLAlchemy>=2.0
pydantic-settings>=2.0
pytest>=8.0
```

- [ ] **Step 2: Install**

Run: `cd source_code && .venv/Scripts/python.exe -m pip install -r requirements.txt`
Expected: installs SQLAlchemy, pydantic-settings, pytest successfully.

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -ra
```

- [ ] **Step 4: Create `tests/conftest.py`**

Sets dummy env vars BEFORE any `transcoder` import (config requires them), and provides an in-memory DB session fixture.

```python
import os

# Required settings must exist before transcoder.config is imported.
os.environ.setdefault("SONARR_URL", "http://sonarr.test")
os.environ.setdefault("SONARR_API_KEY", "test-sonarr-key")
os.environ.setdefault("RADARR_URL", "http://radarr.test")
os.environ.setdefault("RADARR_API_KEY", "test-radarr-key")
os.environ.setdefault("HOSTNAME", "127.0.0.1")
os.environ.setdefault("USERNAME", "tester")
os.environ.setdefault("PASSWORD", "secret")
os.environ.setdefault("HANDBRAKE_CLI", "HandBrakeCLI")

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
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
```

> Note: the `transcoder.db` / `transcoder.models` imports live *inside* the fixture (not at module top) so pytest collection succeeds in Tasks 1–2 before those modules exist.

- [ ] **Step 5: Commit**

```bash
git add source_code/requirements.txt source_code/pytest.ini source_code/tests/conftest.py
git commit -m "chore: add SQLAlchemy/pydantic-settings/pytest and test scaffolding"
```

---

## Task 2: Config via pydantic-settings

**Files:**
- Modify: `source_code/transcoder/config.py`
- Modify: `source_code/transcoder/config.example.py`
- Create: `source_code/.env.example`
- Create: `source_code/tests/__init__.py` (empty — avoids pytest import-mode collisions)
- Modify: `source_code/tests/conftest.py` (rename SFTP env vars)
- Test: `source_code/tests/test_config.py`

- [ ] **Step 0: Fix conftest env vars + add tests package marker**

Create empty `source_code/tests/__init__.py`.

In `source_code/tests/conftest.py`, replace the three SFTP env-var defaults so they match the new prefixed field names (Windows sets `USERNAME`/`HOSTNAME` system-wide, which would shadow `.env`):

```python
os.environ.setdefault("SFTP_HOST", "127.0.0.1")
os.environ.setdefault("SFTP_USERNAME", "tester")
os.environ.setdefault("SFTP_PASSWORD", "secret")
```

(Delete the old `HOSTNAME`/`USERNAME`/`PASSWORD` setdefault lines. Leave the Sonarr/Radarr/HANDBRAKE_CLI lines unchanged.)

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
def test_settings_loads_required_from_env():
    from transcoder.config import settings
    assert settings.SONARR_URL == "http://sonarr.test"
    assert settings.SONARR_API_KEY == "test-sonarr-key"


def test_settings_has_defaults():
    from transcoder.config import settings
    assert settings.PRESET_1080 == "H.265 NVENC 1080p"
    assert settings.DATABASE_URL.startswith("sqlite")
    assert settings.SFTP_PORT == 22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL (current `config.py` has no `DATABASE_URL`; attrs come from a dataclass not env).

- [ ] **Step 3: Rewrite `config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Required (secrets / endpoints) come from .env ---
    # NOTE: SFTP fields are prefixed (SFTP_*) to avoid collision with Windows
    # system env vars like USERNAME/HOSTNAME, which os.environ would otherwise
    # let shadow the .env values (pydantic-settings reads os.environ first).
    SONARR_URL: str
    SONARR_API_KEY: str
    RADARR_URL: str
    RADARR_API_KEY: str
    SFTP_HOST: str
    SFTP_USERNAME: str
    SFTP_PASSWORD: str
    HANDBRAKE_CLI: str

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Create `.env.example`**

`source_code/.env.example`:

```
SONARR_URL=http://your-sonarr-host:8989
SONARR_API_KEY=your_sonarr_api_key
RADARR_URL=http://your-radarr-host:7878
RADARR_API_KEY=your_radarr_api_key
SFTP_HOST=192.168.x.x
SFTP_PORT=22
SFTP_USERNAME=your_sftp_user
SFTP_PASSWORD=your_sftp_password
HANDBRAKE_CLI=C:\path\to\HandBrakeCLI.exe
DATABASE_URL=sqlite:///transcoder.db
```

- [ ] **Step 6: Update `config.example.py`** to a one-line pointer (no longer the config mechanism):

```python
# Configuration now lives in a `.env` file loaded by transcoder/config.py
# (pydantic-settings). Copy `.env.example` to `.env` and fill in your values.
# This file is retained only as a historical note.
```

- [ ] **Step 7: Create the real local `.env`** (NOT committed — gitignored) from your current `config.py` values so the app keeps working. Then commit the rest.

```bash
git add source_code/transcoder/config.py source_code/transcoder/config.example.py source_code/.env.example
git commit -m "feat: load config from .env via pydantic-settings"
```

---

## Task 3: Database layer

**Files:**
- Create: `source_code/transcoder/db.py`
- Test: `source_code/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:

```python
def test_make_engine_and_base_exist():
    from transcoder.db import Base, make_engine
    engine = make_engine("sqlite:///:memory:")
    assert engine is not None
    assert hasattr(Base, "metadata")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_db.py -v`
Expected: FAIL (`No module named transcoder.db`).

- [ ] **Step 3: Create `db.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from transcoder.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    return create_engine(
        url or settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(eng=engine) -> None:
    import transcoder.models  # noqa: F401  (register tables)
    Base.metadata.create_all(eng)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/db.py source_code/tests/test_db.py
git commit -m "feat: add SQLAlchemy engine/session/Base"
```

---

## Task 4: ORM models + key helpers

**Files:**
- Create: `source_code/transcoder/models.py`
- Test: `source_code/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:

```python
from transcoder.models import (
    MediaItem, Job, Exclusion, Setting,
    episode_exclusion_key, movie_exclusion_key,
)


def test_exclusion_key_helpers():
    assert episode_exclusion_key("Breaking Bad", 3, 5) == "Breaking Bad|3|5"
    assert movie_exclusion_key("Inception") == "Inception"


def test_can_persist_media_item_and_job(session):
    item = MediaItem(
        source="sonarr", external_id="42", title="Breaking Bad",
        season=1, episode=1, remote_path="/TVShows/x.mkv",
        resolution=1080, eligibility="needs_transcode",
    )
    session.add(item)
    session.commit()
    job = Job(media_item_id=item.id, state="queued", progress=0)
    session.add(job)
    session.commit()
    assert job.id is not None
    assert job.media_item.title == "Breaking Bad"


def test_setting_roundtrip(session):
    session.add(Setting(key="sonarr_watermark", value="2025-01-01T00:00:00Z"))
    session.commit()
    assert session.get(Setting, "sonarr_watermark").value == "2025-01-01T00:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_models.py -v`
Expected: FAIL (`No module named transcoder.models`).

- [ ] **Step 3: Create `models.py`**

```python
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from transcoder.db import Base


def utcnow() -> dt.datetime:
    # Naive UTC to match SQLite's DateTime columns, which drop tzinfo on
    # read-back; keeps comparisons consistent (no mixed aware/naive errors).
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def episode_exclusion_key(title: str, season: int | str, episode: int | str) -> str:
    return f"{title}|{season}|{episode}"


def movie_exclusion_key(title: str) -> str:
    return title


class MediaItem(Base):
    __tablename__ = "media_item"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_media_source_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(512))
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_path: Mapped[str] = mapped_column(String(1024), default="")
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    languages: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_h265: Mapped[bool] = mapped_column(Boolean, default=False)
    eligibility: Mapped[str] = mapped_column(String(32), default="needs_transcode")
    last_scanned_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="media_item")


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id"))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    original_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reduction_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    media_item: Mapped["MediaItem"] = relationship(back_populates="jobs")


class Exclusion(Base):
    __tablename__ = "exclusion"
    __table_args__ = (
        UniqueConstraint("source", "key", name="uq_exclusion_source_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(640))
    reason: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/models.py source_code/tests/test_models.py
git commit -m "feat: add media_item/job/exclusion/setting models"
```

---

## Task 5: Shared repo helpers

**Files:**
- Create: `source_code/transcoder/repo.py`
- Test: `source_code/tests/test_repo.py`

- [ ] **Step 1: Write the failing test**

`tests/test_repo.py`:

```python
from transcoder.models import MediaItem, Exclusion
from transcoder import repo


def test_upsert_media_item_is_idempotent(session):
    repo.upsert_media_item(
        session, source="sonarr", external_id="7", title="A",
        remote_path="/TVShows/a.mkv", resolution=1080,
    )
    repo.upsert_media_item(
        session, source="sonarr", external_id="7", title="A (renamed)",
        remote_path="/TVShows/a.mkv", resolution=2160,
    )
    session.commit()
    items = session.query(MediaItem).all()
    assert len(items) == 1
    assert items[0].title == "A (renamed)"
    assert items[0].resolution == 2160


def test_setting_helpers(session):
    assert repo.get_setting(session, "k") is None
    repo.set_setting(session, "k", "v1")
    repo.set_setting(session, "k", "v2")
    assert repo.get_setting(session, "k") == "v2"


def test_excluded_keys(session):
    session.add(Exclusion(source="sonarr", key="A|1|1", reason="output_larger"))
    session.commit()
    assert repo.excluded_keys(session, "sonarr") == {"A|1|1"}
    assert repo.excluded_keys(session, "radarr") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_repo.py -v`
Expected: FAIL (`No module named transcoder.repo`).

- [ ] **Step 3: Create `repo.py`**

```python
from transcoder.models import Exclusion, MediaItem, Setting, utcnow


def upsert_media_item(session, *, source: str, external_id: str, **fields) -> MediaItem:
    item = (
        session.query(MediaItem)
        .filter_by(source=source, external_id=external_id)
        .one_or_none()
    )
    if item is None:
        item = MediaItem(source=source, external_id=external_id)
        session.add(item)
    for key, value in fields.items():
        setattr(item, key, value)
    item.last_scanned_at = utcnow()
    return item


def get_setting(session, key: str):
    row = session.get(Setting, key)
    return row.value if row else None


def set_setting(session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


def excluded_keys(session, source: str) -> set[str]:
    return {
        e.key for e in session.query(Exclusion).filter_by(source=source).all()
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/repo.py source_code/tests/test_repo.py
git commit -m "feat: add repo helpers (upsert, settings, exclusions)"
```

---

## Task 6: Eligibility rule

**Files:**
- Create: `source_code/transcoder/engine/__init__.py` (empty)
- Create: `source_code/transcoder/engine/eligibility.py`
- Test: `source_code/tests/test_eligibility.py`

- [ ] **Step 1: Write the failing test**

`tests/test_eligibility.py`:

```python
from transcoder.engine.eligibility import compute_eligibility


def test_eligibility_rules():
    assert compute_eligibility(1080, is_h265=False, excluded=False) == "needs_transcode"
    assert compute_eligibility(2160, is_h265=False, excluded=False) == "needs_transcode"
    assert compute_eligibility(720, is_h265=False, excluded=False) == "below_1080p"
    assert compute_eligibility(1080, is_h265=True, excluded=False) == "already_h265"
    assert compute_eligibility(1080, is_h265=False, excluded=True) == "excluded"
    # excluded wins over everything
    assert compute_eligibility(720, is_h265=True, excluded=True) == "excluded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_eligibility.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Create the files**

`engine/__init__.py`: empty.

`engine/eligibility.py`:

```python
def compute_eligibility(resolution: int, is_h265: bool, excluded: bool) -> str:
    if excluded:
        return "excluded"
    if is_h265:
        return "already_h265"
    if resolution < 1080:
        return "below_1080p"
    return "needs_transcode"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_eligibility.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/engine/__init__.py source_code/transcoder/engine/eligibility.py source_code/tests/test_eligibility.py
git commit -m "feat: add eligibility rule"
```

---

## Task 7: Legacy migration

**Files:**
- Create: `source_code/transcoder/migrate.py`
- Test: `source_code/tests/test_migrate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_migrate.py`:

```python
import os

from transcoder import migrate
from transcoder.config import settings
from transcoder.models import Exclusion, Setting


def test_migrate_legacy_files(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(settings.EPISODE_EXCLUSION_CSV, "w", encoding="utf-8", newline="") as f:
        f.write("Breaking Bad,3,5\n")
    with open(settings.MOVIE_EXCLUSION_CSV, "w", encoding="utf-8", newline="") as f:
        f.write("Inception\n")
    with open(settings.LAST_HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write("2025-01-01T00:00:00Z")

    result = migrate.migrate_legacy(session)

    assert result == {"episodes": 1, "movies": 1, "watermark": True}
    eps = session.query(Exclusion).filter_by(source="sonarr").all()
    assert eps[0].key == "Breaking Bad|3|5"
    mvs = session.query(Exclusion).filter_by(source="radarr").all()
    assert mvs[0].key == "Inception"
    assert session.get(Setting, "sonarr_watermark").value == "2025-01-01T00:00:00Z"
    # originals renamed, not left in place
    assert not os.path.exists(settings.EPISODE_EXCLUSION_CSV)
    assert os.path.exists(settings.EPISODE_EXCLUSION_CSV + ".migrated")


def test_migrate_is_idempotent_and_safe_when_absent(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert migrate.migrate_legacy(session) == {"episodes": 0, "movies": 0, "watermark": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_migrate.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Create `migrate.py`**

```python
import csv
import os

from transcoder.config import settings
from transcoder.models import Exclusion, Setting, episode_exclusion_key, movie_exclusion_key


def _add_exclusion(session, source: str, key: str) -> bool:
    exists = (
        session.query(Exclusion).filter_by(source=source, key=key).first() is not None
    )
    if exists:
        return False
    session.add(Exclusion(source=source, key=key, reason="output_larger"))
    return True


def migrate_legacy(session) -> dict:
    result = {"episodes": 0, "movies": 0, "watermark": False}
    to_rename = []

    ep_csv = settings.EPISODE_EXCLUSION_CSV
    if os.path.exists(ep_csv):
        with open(ep_csv, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 3:
                    continue
                if _add_exclusion(session, "sonarr",
                                  episode_exclusion_key(row[0], row[1], row[2])):
                    result["episodes"] += 1
        to_rename.append(ep_csv)

    mv_csv = settings.MOVIE_EXCLUSION_CSV
    if os.path.exists(mv_csv):
        with open(mv_csv, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row:
                    continue
                if _add_exclusion(session, "radarr", movie_exclusion_key(row[0])):
                    result["movies"] += 1
        to_rename.append(mv_csv)

    hist = settings.LAST_HISTORY_FILE
    if os.path.exists(hist):
        with open(hist, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw and session.get(Setting, "sonarr_watermark") is None:
            session.add(Setting(key="sonarr_watermark", value=raw))
            result["watermark"] = True
        to_rename.append(hist)

    # Persist all rows BEFORE touching the filesystem, so a crash can't leave
    # legacy data neither on disk nor in the DB. os.replace is atomic and
    # overwrites an existing *.migrated (os.rename raises FileExistsError on
    # Windows if the destination already exists).
    session.commit()
    for path in to_rename:
        os.replace(path, path + ".migrated")

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_migrate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/migrate.py source_code/tests/test_migrate.py
git commit -m "feat: migrate legacy CSV/timestamp state into the database"
```

---

## Task 8: Convert progress parser + callback

**Files:**
- Modify: `source_code/transcoder/convert.py`
- Test: `source_code/tests/test_convert_progress.py`

- [ ] **Step 1: Write the failing test**

`tests/test_convert_progress.py`:

```python
from transcoder.convert import parse_handbrake_progress


def test_parse_progress_matches():
    line = "Encoding: task 1 of 1, 42.13 %"
    assert parse_handbrake_progress(line) == 42


def test_parse_progress_none_for_other_lines():
    assert parse_handbrake_progress("Scanning title 1...") is None
    assert parse_handbrake_progress("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_convert_progress.py -v`
Expected: FAIL (`parse_handbrake_progress` not defined).

- [ ] **Step 3: Modify `convert.py`**

Add the pure parser and wire it into the loop via an optional `progress_cb`. Replace the dead `1 == 1` block. Full new file:

```python
import os
import re
import subprocess
import time

from transcoder.config import settings

_PROGRESS_RE = re.compile(r"Encoding: .*?\s(\d{1,3})\.\d+ %")


def parse_handbrake_progress(line: str):
    match = _PROGRESS_RE.search(line)
    return int(match.group(1)) if match else None


def convert_with_handbrake(input_file, output_filename, preset, progress_cb=None):
    output_file = settings.OUTPUT_FOLDER + output_filename

    command = [
        settings.HANDBRAKE_CLI,
        "-i", input_file,
        "-o", output_file,
        "--preset", preset,
        "--all-audio",
        "-f", settings.OUTPUT_FORMAT,
        "--all-subtitles",
    ]

    start = time.time()
    print(f"Conversion Started for {output_filename}")
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )

    for line in process.stdout:
        pct = parse_handbrake_progress(line)
        if pct is not None and progress_cb is not None:
            try:
                progress_cb(pct)
            except Exception:
                # A progress-update failure (e.g. a transient DB write error)
                # must not abort the transcode or orphan the subprocess.
                pass

    process.wait()
    elapsed = time.time() - start

    if process.returncode != 0:
        print("HandBrake conversion failed. Skipping this file.")
        if os.path.exists(input_file):
            os.remove(input_file)
            print(f"Deleted temporary file: {input_file}")
        return None, False

    original_size = os.path.getsize(input_file) / (1024 * 1024)
    new_size = os.path.getsize(output_file) / (1024 * 1024)
    reduction = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
    print(f"Size Reduction: {reduction:.2f}% (took {elapsed:.0f}s)")

    os.remove(input_file)
    print(f"Deleted temporary file: {input_file}")

    return output_file, new_size >= original_size
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_convert_progress.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/convert.py source_code/tests/test_convert_progress.py
git commit -m "feat: capture HandBrake progress via callback"
```

---

## Task 9: Discovery (Sonarr + Radarr)

**Files:**
- Modify: `source_code/transcoder/radarr_client.py` (include ids)
- Create: `source_code/transcoder/engine/discovery.py`
- Test: `source_code/tests/test_discovery.py`

- [ ] **Step 1: Write the failing test**

`tests/test_discovery.py` (uses fake clients — no network):

```python
from transcoder.engine import discovery
from transcoder.models import MediaItem, Exclusion


class FakeSonarr:
    def get_all_series(self):
        return [{"id": 1, "title": "Show A"}]

    def get_episodes(self, series_id):
        return [
            {"hasFile": True, "episodeFileId": 100, "seasonNumber": 1, "episodeNumber": 1},
            {"hasFile": True, "episodeFileId": 101, "seasonNumber": 1, "episodeNumber": 2},
            {"hasFile": False, "episodeFileId": 0, "seasonNumber": 1, "episodeNumber": 3},
        ]

    def get_episode_file(self, fid):
        files = {
            100: {"path": "/TVShows/a1.mkv", "size": 999},   # 1080, not h265
            101: {"path": "/TVShows/a2.mkv", "size": 999},   # 720, below
        }
        return files[fid]

    def extract_resolution(self, ef):
        return 1080 if ef["path"].endswith("a1.mkv") else 720

    def is_h265_encoded(self, ef):
        return False

    def extract_quality(self, ef):
        return "HDTV-1080p"

    def extract_languages(self, ef):
        return "ENG"


def test_discover_sonarr_populates_items_with_eligibility(session):
    count = discovery.discover_sonarr(session, FakeSonarr(), scope="all")
    assert count == 2  # only episodes with files
    items = {i.external_id: i for i in session.query(MediaItem).all()}
    assert items["100"].eligibility == "needs_transcode"
    assert items["101"].eligibility == "below_1080p"
    assert items["100"].title == "Show A"
    assert items["100"].season == 1 and items["100"].episode == 1


def test_discover_sonarr_marks_excluded(session):
    session.add(Exclusion(source="sonarr", key="Show A|1|1", reason="output_larger"))
    session.commit()
    discovery.discover_sonarr(session, FakeSonarr(), scope="all")
    item = session.query(MediaItem).filter_by(external_id="100").one()
    assert item.eligibility == "excluded"


class FakeRadarr:
    def get_all_movies(self):
        return ["raw"]

    def filter_non_h265_movies(self, movies):
        return [{
            "title": "Movie X", "codec": "h264", "path": "/movies/x.mkv",
            "resolution": 2160, "quality": "Bluray-2160p", "languages": "ENG",
            "year": 2020, "movie_id": 55, "external_id": "555",
        }]


def test_discover_radarr_populates_items(session):
    count = discovery.discover_radarr(session, FakeRadarr())
    assert count == 1
    item = session.query(MediaItem).filter_by(source="radarr").one()
    assert item.external_id == "555"
    assert item.eligibility == "needs_transcode"
    assert item.year == 2020
    assert item.parent_id == 55
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_discovery.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Modify `radarr_client.py`** so `filter_non_h265_movies` includes ids the engine needs. Replace the appended dict (lines ~37-45) with:

```python
                non_h265.append({
                    "title": movie["title"],
                    "codec": video_codec or "unknown",
                    "path": movie_file.get("path", "unknown"),
                    "resolution": movie_file.get("quality").get("quality").get("resolution"),
                    "quality": movie_file.get("quality").get("quality").get("name"),
                    "languages": languages,
                    "year": movie["year"],
                    "movie_id": movie["id"],
                    "external_id": str(movie_file.get("id")),
                })
```

- [ ] **Step 4: Create `engine/discovery.py`**

```python
import datetime as dt

from transcoder import repo
from transcoder.engine.eligibility import compute_eligibility
from transcoder.history import _parse_iso_z
from transcoder.models import episode_exclusion_key, movie_exclusion_key


def _watermark_iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def discover_sonarr(session, client, scope: str = "all", target_title=None) -> int:
    excluded = repo.excluded_keys(session, "sonarr")
    watermark = None
    recent_ids = set()
    newest = None

    if scope == "new":
        raw = repo.get_setting(session, "sonarr_watermark")
        watermark = _parse_iso_z(raw) if raw else None
        recent_ids, newest = client.get_recent_series_ids(watermark)

    series_list = client.get_all_series()
    if target_title:
        series_list = [s for s in series_list if s["title"].lower() == target_title.lower()]
    elif scope == "new" and watermark is not None:
        series_list = [s for s in series_list if s["id"] in recent_ids]

    count = 0
    for series in series_list:
        for ep in client.get_episodes(series["id"]):
            if not ep.get("hasFile"):
                continue
            ef = client.get_episode_file(ep["episodeFileId"])
            if not ef:
                continue
            resolution = client.extract_resolution(ef)
            is_h265 = client.is_h265_encoded(ef)
            key = episode_exclusion_key(series["title"], ep["seasonNumber"], ep["episodeNumber"])
            repo.upsert_media_item(
                session,
                source="sonarr",
                external_id=str(ep["episodeFileId"]),
                parent_id=series["id"],
                title=series["title"],
                season=ep["seasonNumber"],
                episode=ep["episodeNumber"],
                remote_path=ef.get("path", ""),
                resolution=resolution,
                quality=client.extract_quality(ef),
                languages=client.extract_languages(ef),
                size_bytes=ef.get("size"),
                is_h265=is_h265,
                codec=None,
                eligibility=compute_eligibility(resolution, is_h265, key in excluded),
            )
            count += 1

    if scope == "new" and newest is not None:
        repo.set_setting(session, "sonarr_watermark", _watermark_iso(newest))

    session.commit()
    return count


def discover_radarr(session, client, target_movie=None) -> int:
    excluded = repo.excluded_keys(session, "radarr")
    rows = client.filter_non_h265_movies(client.get_all_movies())
    if target_movie:
        rows = [r for r in rows if r["title"].lower() == target_movie.lower()]

    count = 0
    for r in rows:
        key = movie_exclusion_key(r["title"])
        resolution = r["resolution"] or 0
        repo.upsert_media_item(
            session,
            source="radarr",
            external_id=r["external_id"],
            parent_id=r["movie_id"],
            title=r["title"],
            year=r["year"],
            remote_path=r["path"],
            resolution=resolution,
            quality=r["quality"],
            languages=r["languages"],
            codec=r["codec"],
            is_h265=False,
            eligibility=compute_eligibility(resolution, False, key in excluded),
        )
        count += 1

    session.commit()
    return count
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_discovery.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/engine/discovery.py source_code/transcoder/radarr_client.py source_code/tests/test_discovery.py
git commit -m "feat: discovery populates media_items with eligibility"
```

---

## Task 10: Queue

**Files:**
- Create: `source_code/transcoder/engine/queue.py`
- Test: `source_code/tests/test_queue.py`

- [ ] **Step 1: Write the failing test**

`tests/test_queue.py`:

```python
from transcoder.engine.queue import enqueue_eligible
from transcoder.models import Job, MediaItem


def _add(session, **kw):
    item = MediaItem(source="sonarr", remote_path="/x.mkv", **kw)
    session.add(item)
    session.commit()
    return item


def test_enqueue_only_eligible(session):
    _add(session, external_id="1", title="A", eligibility="needs_transcode")
    _add(session, external_id="2", title="B", eligibility="already_h265")
    _add(session, external_id="3", title="C", eligibility="below_1080p")
    created = enqueue_eligible(session)
    assert created == 1
    assert session.query(Job).count() == 1


def test_enqueue_dedupes_active_jobs(session):
    item = _add(session, external_id="1", title="A", eligibility="needs_transcode")
    session.add(Job(media_item_id=item.id, state="queued"))
    session.commit()
    created = enqueue_eligible(session)
    assert created == 0
    assert session.query(Job).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_queue.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Create `engine/queue.py`**

```python
from transcoder.models import Job, MediaItem


def enqueue_eligible(session, source: str | None = None) -> int:
    query = session.query(MediaItem).filter(
        MediaItem.eligibility == "needs_transcode"
    )
    if source:
        query = query.filter(MediaItem.source == source)

    created = 0
    for item in query.all():
        active = (
            session.query(Job)
            .filter(Job.media_item_id == item.id, Job.state.in_(["queued", "running"]))
            .first()
        )
        if active:
            continue
        session.add(Job(media_item_id=item.id, state="queued"))
        created += 1

    session.commit()
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_queue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/engine/queue.py source_code/tests/test_queue.py
git commit -m "feat: enqueue eligible items as jobs with dedupe"
```

---

## Task 11: Worker

**Files:**
- Create: `source_code/transcoder/engine/worker.py`
- Test: `source_code/tests/test_worker.py`

- [ ] **Step 1: Write the failing test**

`tests/test_worker.py` (all IO injected — no network/subprocess/disk for size we control via fakes):

```python
import os

from transcoder.engine.worker import process_one_job, process_queue
from transcoder.models import Exclusion, Job, MediaItem


class FakeClient:
    def __init__(self):
        self.imported = []

    def manual_import_one(self, path):
        self.imported.append(path)


def _item(session, **kw):
    defaults = dict(
        source="sonarr", external_id="1", title="Show A", season=1, episode=1,
        remote_path="/TVShows/a.mkv", resolution=1080, quality="HDTV-1080p",
        languages="ENG", eligibility="needs_transcode",
    )
    defaults.update(kw)
    item = MediaItem(**defaults)
    session.add(item)
    session.commit()
    return item


def _make_io(smaller=True, fail=False, sizes=(1000, 400)):
    calls = {"download": [], "upload": [], "removed": []}

    def download(host, port, user, pw, remote, local):
        calls["download"].append((remote, local))
        return {"success": True}

    def upload(host, port, user, pw, local, remote):
        calls["upload"].append((local, remote))
        return {"success": True}

    def convert(tmp, out_name, preset, progress_cb=None):
        if progress_cb:
            progress_cb(50)
            progress_cb(100)
        if fail:
            return None, False
        return ("./out/" + out_name, not smaller)

    return calls, download, upload, convert


def test_worker_success_smaller(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(smaller=True)
    client = FakeClient()
    process_one_job(session, job, {"sonarr": client},
                    download=download, upload=upload, convert=convert)

    assert job.state == "done"
    assert job.progress == 100
    assert len(calls["upload"]) == 1
    assert len(client.imported) == 1
    assert job.preset == "H.265 NVENC 1080p"


def test_worker_larger_excludes(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(smaller=False)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "skipped_larger"
    assert session.query(Exclusion).filter_by(source="sonarr", key="Show A|1|1").count() == 1
    assert item.eligibility == "excluded"
    assert len(calls["upload"]) == 0


def test_worker_convert_failure(session, monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(fail=True)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "failed"
    assert job.error_message


def test_process_queue_drains(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    for i in range(3):
        item = _item(session, external_id=str(i))
        session.add(Job(media_item_id=item.id, state="queued"))
    session.commit()

    calls, download, upload, convert = _make_io(smaller=True)
    processed = process_queue(session, {"sonarr": FakeClient()},
                              download=download, upload=upload, convert=convert)
    assert processed == 3
    assert session.query(Job).filter_by(state="done").count() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Create `engine/worker.py`**

```python
import os
import re

from transcoder.config import settings
from transcoder.convert import convert_with_handbrake
from transcoder.models import Exclusion, Job, episode_exclusion_key, movie_exclusion_key, utcnow
from transcoder.sftp_client import download_file_via_sftp, upload_file_via_sftp


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9 \-]", "", name)


def _local_path(item) -> str:
    if item.source == "sonarr":
        return item.remote_path.replace("/TVShows/", settings.LOCAL_FOLDER)
    return item.remote_path.replace("/movies/", settings.LOCAL_FOLDER_MOVIES).replace("/", "\\")


def _output_name(item) -> str:
    title = _sanitize(item.title)
    if item.source == "sonarr":
        return (
            f"{title} - S{item.season:02}E{item.episode:02} - h265 - "
            f"[{item.languages}] {item.quality} {settings.RELEASE_TAG}.mkv"
        )
    return f"{title} ({item.year}) [h265] [{item.languages}] {item.quality} {settings.RELEASE_TAG}.mkv"


def _exclusion_key(item) -> str:
    if item.source == "sonarr":
        return episode_exclusion_key(item.title, item.season, item.episode)
    return movie_exclusion_key(item.title)


def process_one_job(
    session,
    job,
    clients,
    *,
    download=download_file_via_sftp,
    upload=upload_file_via_sftp,
    convert=convert_with_handbrake,
):
    item = job.media_item
    client = clients[item.source]

    job.state = "running"
    job.started_at = utcnow()
    job.progress = 0
    job.preset = settings.PRESET_4K if item.resolution > 1080 else settings.PRESET_1080
    session.commit()

    try:
        os.makedirs("./tmp", exist_ok=True)
        file_path = _local_path(item)
        tmp_file = os.path.join("./tmp", os.path.basename(file_path))
        download(settings.SFTP_HOST, settings.SFTP_PORT, settings.SFTP_USERNAME,
                 settings.SFTP_PASSWORD, file_path, tmp_file)

        original_size = os.path.getsize(tmp_file)
        out_name = _output_name(item)

        def cb(pct):
            job.progress = pct
            session.commit()

        output_file, exclude_flag = convert(tmp_file, out_name, job.preset, progress_cb=cb)

        if output_file is None:
            job.state = "failed"
            job.error_message = "HandBrake conversion failed"
            job.finished_at = utcnow()
            session.commit()
            return job

        job.original_size = original_size
        job.output_size = os.path.getsize(output_file)
        if job.original_size:
            job.reduction_pct = (job.original_size - job.output_size) / job.original_size * 100

        if exclude_flag:
            session.add(Exclusion(source=item.source, key=_exclusion_key(item),
                                  reason="output_larger"))
            item.eligibility = "excluded"
            job.state = "skipped_larger"
        else:
            upload(settings.SFTP_HOST, settings.SFTP_PORT, settings.SFTP_USERNAME,
                   settings.SFTP_PASSWORD, output_file, settings.WATCH_FOLDER + out_name)
            client.manual_import_one(output_file)
            item.eligibility = "already_h265"
            job.output_filename = out_name
            job.state = "done"

        if os.path.exists(output_file):
            os.remove(output_file)

        job.finished_at = utcnow()
        session.commit()
        return job

    except Exception as exc:  # noqa: BLE001 — record failure, keep draining queue
        job.state = "failed"
        job.error_message = str(exc)
        job.finished_at = utcnow()
        session.commit()
        return job


def process_queue(session, clients, *, limit: int | None = None, **io) -> int:
    processed = 0
    while True:
        job = (
            session.query(Job)
            .filter(Job.state == "queued")
            .order_by(Job.id)
            .first()
        )
        if job is None:
            break
        process_one_job(session, job, clients, **io)
        processed += 1
        if limit and processed >= limit:
            break
    return processed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/engine/worker.py source_code/tests/test_worker.py
git commit -m "feat: serial worker processes one job at a time"
```

---

## Task 12: Logging refactor

**Files:**
- Modify: `source_code/transcoder/logging_setup.py`

- [ ] **Step 1: Rewrite `logging_setup.py`** (drop the `print` monkeypatch; provide real leveled logging)

```python
import datetime as dt
import logging
import os


def init_logging(level: int = logging.INFO) -> logging.Logger:
    os.makedirs("log", exist_ok=True)
    fname = dt.datetime.now().strftime("log/%Y-%m-%d_%H-%M-%S.log")
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(fname, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("transcoder")
```

- [ ] **Step 2: Verify nothing imports the old behavior**

Run: `cd source_code && grep -rn "builtins.print" transcoder/ || echo "clean"`
Expected: `clean`.

> Note: existing `print(...)` calls in `convert.py`, `sftp_client.py`, and the API clients still go to stdout. Since `basicConfig` adds a `StreamHandler`, they remain visible on the console; converting each to `logger` calls is a low-value follow-up tracked for a later cleanup, not required for Cycle 1 behavior.

- [ ] **Step 3: Commit**

```bash
git add source_code/transcoder/logging_setup.py
git commit -m "refactor: real leveled logging, drop print monkeypatch"
```

---

## Task 13: CLI rewrite (scan / run / queue)

**Files:**
- Modify: `source_code/transcoder/cli.py`
- Test: `source_code/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py` (tests argument parsing only; the heavy lifting is already covered by engine tests):

```python
from transcoder.cli import build_parser


def test_parser_defaults():
    args = build_parser().parse_args(["run", "all"])
    assert args.command == "run"
    assert args.app == "all"
    assert args.scope == "all"


def test_parser_scan_with_filters():
    args = build_parser().parse_args(["scan", "sonarr", "new", "--show", "Breaking Bad"])
    assert args.command == "scan"
    assert args.app == "sonarr"
    assert args.scope == "new"
    assert args.show == "Breaking Bad"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL (`build_parser` not defined).

- [ ] **Step 3: Rewrite `cli.py`**

```python
#!/usr/bin/env python3
import argparse
import logging

from transcoder.logging_setup import init_logging
from transcoder.config import settings
from transcoder.db import SessionLocal, init_db
from transcoder.migrate import migrate_legacy
from transcoder.sonarr_client import SonarrClient
from transcoder.radarr_client import RadarrClient
from transcoder.engine.discovery import discover_sonarr, discover_radarr
from transcoder.engine.queue import enqueue_eligible
from transcoder.engine.worker import process_queue
from transcoder.models import Job

log = logging.getLogger("transcoder")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcode Sonarr/Radarr media to H.265")
    parser.add_argument("command", choices=["scan", "run", "queue"],
                        help="scan: discover only; run: discover+enqueue+process; queue: list jobs")
    parser.add_argument("app", nargs="?", choices=["all", "sonarr", "radarr"], default="all")
    parser.add_argument("scope", nargs="?", choices=["all", "new"], default="all")
    parser.add_argument("--show", help="Sonarr: only this exact series title")
    parser.add_argument("--movie", help="Radarr: only this exact movie title")
    return parser


def _discover(session, app, scope, show, movie):
    if app in ("all", "sonarr"):
        n = discover_sonarr(session, SonarrClient(settings.SONARR_URL, settings.SONARR_API_KEY),
                            scope=scope, target_title=show)
        log.info("Sonarr discovery: %s items", n)
    if app in ("all", "radarr"):
        n = discover_radarr(session, RadarrClient(settings.RADARR_URL, settings.RADARR_API_KEY),
                            target_movie=movie)
        log.info("Radarr discovery: %s items", n)


def main() -> None:
    init_logging()
    init_db()
    args = build_parser().parse_args()

    clients = {
        "sonarr": SonarrClient(settings.SONARR_URL, settings.SONARR_API_KEY),
        "radarr": RadarrClient(settings.RADARR_URL, settings.RADARR_API_KEY),
    }

    with SessionLocal() as session:
        migrate_legacy(session)

        if args.command == "queue":
            for job in session.query(Job).order_by(Job.id).all():
                log.info("Job %s | %s | progress=%s%% | item=%s",
                         job.id, job.state, job.progress, job.media_item.title)
            return

        _discover(session, args.app, args.scope, args.show, args.movie)

        if args.command == "run":
            created = enqueue_eligible(session,
                                      source=None if args.app == "all" else args.app)
            log.info("Enqueued %s jobs", created)
            processed = process_queue(session, clients)
            log.info("Processed %s jobs", processed)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/cli.py source_code/tests/test_cli.py
git commit -m "feat: CLI scan/run/queue backed by the engine + DB"
```

---

## Task 14: Cleanup legacy modules & docs

**Files:**
- Delete: `source_code/transcoder/exclusion.py` (logic moved to DB; only migrate uses CSVs now)
- Keep: `source_code/transcoder/history.py` (its `_parse_iso_z` is still used by discovery)
- Modify: `CLAUDE.md` (update commands + state-file description)

- [ ] **Step 1: Confirm `exclusion.py` is unused**

Run: `cd source_code && grep -rn "from transcoder.exclusion\|import exclusion" transcoder/ tests/ || echo "unused"`
Expected: `unused`.

- [ ] **Step 2: Delete it**

```bash
git rm source_code/transcoder/exclusion.py
```

- [ ] **Step 3: Update `CLAUDE.md`** — replace the **Commands** Run block with:

````markdown
**Run:**
```bash
cd source_code
python -m transcoder.cli <command> [app] [scope] [--show "Title"] [--movie "Title"]
# command: scan | run | queue
# app: all | sonarr | radarr (default all)
# scope: all | new (default all)
```
````

And replace the **State files** section with:

```markdown
**State** lives in a SQLite database (`source_code/transcoder.db`): `media_item`, `job`,
`exclusion`, `setting` tables. Legacy `excluded_*.csv` / `last_history_timestamp.txt` are
auto-imported on first run and renamed `*.migrated`. Config is loaded from `source_code/.env`.
```

- [ ] **Step 4: Run the full suite once more**

Run: `cd source_code && .venv/Scripts/python.exe -m pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove legacy exclusion module, update docs"
```

---

## Task 15: Manual end-to-end smoke (real services)

> This task requires your real `.env` and live Sonarr/Radarr/SFTP. Run with a single-title filter to keep it small and safe.

- [ ] **Step 1: Ensure `.env` exists** in `source_code/` with your real values (copied from the old `config.py`).

- [ ] **Step 2: Scan one show (no transcoding)**

Run: `cd source_code && .venv/Scripts/python.exe -m transcoder.cli scan sonarr all --show "<a known SD/h264 show>"`
Expected: log shows "Sonarr discovery: N items"; `transcoder.db` created.

- [ ] **Step 3: Inspect the queue/library**

Run: `cd source_code && .venv/Scripts/python.exe -m transcoder.cli queue`
Expected: lists discovered items' jobs (none yet — `scan` doesn't enqueue).

- [ ] **Step 4: Full run on one movie**

Run: `cd source_code && .venv/Scripts/python.exe -m transcoder.cli run radarr all --movie "<a known h264 movie>"`
Expected: discovers, enqueues, downloads, transcodes, and either imports (if smaller) or records `skipped_larger`. Verify in `queue` output and in Radarr.

- [ ] **Step 5: Confirm credential rotation**

Per the spec security note, rotate the Sonarr/Radarr API keys and SFTP password (they were previously in committed source / chat), then update `.env`. No commit needed (`.env` is gitignored).

---

## Self-Review Notes (completed by plan author)

- **Spec coverage:** data model (Tasks 3–5), engine split discovery/queue/worker (Tasks 9–11), progress capture (Task 8), config/secrets (Task 2), logging (Task 12), CLI (Task 13), migration (Task 7), testing throughout, Radarr-always-all-scope preserved (Task 9). ✔
- **Type consistency:** `process_one_job`/`process_queue` share the `download/upload/convert` injection names; `clients` is a `{source: client}` dict in both worker and CLI; `external_id` is always stored as `str`; exclusion key helpers used identically in discovery, worker, and migrate. ✔
- **Placeholder scan:** no TBD/TODO; every code step contains full code. ✔
