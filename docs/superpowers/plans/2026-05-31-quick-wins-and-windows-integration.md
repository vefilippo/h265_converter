# Quick Wins + Windows Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver three quick service improvements (season/episode on jobs, log file cleanup, DB backup) then a Windows system tray launcher with health indicator and toast notifications.

**Architecture:** Cycle 5A touches only existing Python/FastAPI/React files; no new dependencies. Cycle 5B adds a standalone `tray.pyw` launcher (pystray + Pillow + winotify) that polls the API — the server itself stays platform-neutral.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, React 18 + TypeScript + Vite, pystray ≥0.19, Pillow ≥10, winotify ≥1.1

---

## Task 0: Merge job-phases-and-logs → master (prerequisite)

**Files:** none changed (git only)

- [ ] **Step 1: Verify tests pass on the feature branch**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass (no failures).

- [ ] **Step 2: Merge to master**

```powershell
git checkout master
git merge --no-ff job-phases-and-logs -m "Merge: job phases, live progress & per-job logs (Cycle A+B)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 3: Delete the feature branch**

```powershell
git branch -d job-phases-and-logs
```

- [ ] **Step 4: Verify tests still pass on master**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

---

## Task 1: Create Cycle 5A branch

**Files:** none

- [ ] **Step 1: Create and switch to branch**

```powershell
git checkout -b cycle-5a-quick-wins
```

---

## Task 2: Season/episode in job responses (backend)

**Files:**
- Modify: `source_code/transcoder/api/schemas.py`
- Modify: `source_code/transcoder/api/routers/jobs.py`
- Modify: `source_code/tests/test_api_jobs.py`

- [ ] **Step 1: Write the failing test**

In `source_code/tests/test_api_jobs.py`, add after `test_jobs_list_includes_phase`:

```python
def test_job_includes_season_and_episode(api):
    client, Session = api
    _seed_item(Session, title="Breaking Bad", season=2, episode=9)
    client.post("/api/enqueue", json={})
    body = client.get("/api/jobs").json()
    item = body["items"][0]
    assert item["title"] == "Breaking Bad"
    assert item["season"] == 2
    assert item["episode"] == 9


def test_movie_job_has_null_season_episode(api):
    client, Session = api
    _seed_item(Session, source="radarr", external_id="99", title="Inception",
               season=None, episode=None)
    client.post("/api/enqueue", json={})
    body = client.get("/api/jobs").json()
    item = body["items"][0]
    assert item["season"] is None
    assert item["episode"] is None
```

- [ ] **Step 2: Run to confirm failure**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest tests/test_api_jobs.py::test_job_includes_season_and_episode -v
```

Expected: FAIL — `KeyError: 'season'` or `AssertionError`.

- [ ] **Step 3: Add season/episode to JobOut**

In `source_code/transcoder/api/schemas.py`, replace:

```python
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
    phase: str | None = None
    created_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
```

with:

```python
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
```

- [ ] **Step 4: Populate season/episode in _to_out()**

In `source_code/transcoder/api/routers/jobs.py`, replace:

```python
def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.title = job.media_item.title if job.media_item else None
    return out
```

with:

```python
def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    if job.media_item:
        out.title = job.media_item.title
        out.season = job.media_item.season
        out.episode = job.media_item.episode
    return out
```

- [ ] **Step 5: Run tests to confirm pass**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest tests/test_api_jobs.py -v
```

Expected: all tests in `test_api_jobs.py` pass.

- [ ] **Step 6: Commit**

```powershell
git add source_code/transcoder/api/schemas.py source_code/transcoder/api/routers/jobs.py source_code/tests/test_api_jobs.py
git commit -m "feat: expose season/episode on JobOut

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Season/episode display in the frontend

**Files:**
- Modify: `source_code/web/src/api/types.ts`
- Modify: `source_code/web/src/components/ui/badge.tsx`
- Modify: `source_code/web/src/pages/Jobs.tsx`
- Modify: `source_code/web/src/pages/Dashboard.tsx`
- Modify: `source_code/web/src/pages/Jobs.test.tsx`

- [ ] **Step 1: Add season/episode to the Job type**

In `source_code/web/src/api/types.ts`, replace:

```typescript
export interface Job {
  id: number; media_item_id: number; state: string; progress: number;
  preset: string | null; original_size: number | null; output_size: number | null;
  reduction_pct: number | null; output_filename: string | null;
  error_message: string | null; title: string | null; phase: string | null;
  created_at: string | null; started_at: string | null; finished_at: string | null;
}
```

with:

```typescript
export interface Job {
  id: number; media_item_id: number; state: string; progress: number;
  preset: string | null; original_size: number | null; output_size: number | null;
  reduction_pct: number | null; output_filename: string | null;
  error_message: string | null; title: string | null;
  season: number | null; episode: number | null;
  phase: string | null;
  created_at: string | null; started_at: string | null; finished_at: string | null;
}
```

- [ ] **Step 2: Add jobTitle helper to badge.tsx**

In `source_code/web/src/components/ui/badge.tsx`, add after `jobStateLabel`:

```typescript
export function jobTitle(job: { title: string | null; season: number | null; episode: number | null }): string {
  if (job.season != null && job.episode != null) {
    const s = String(job.season).padStart(2, "0");
    const e = String(job.episode).padStart(2, "0");
    return `${job.title ?? "—"} — S${s}E${e}`;
  }
  return job.title ?? "—";
}
```

- [ ] **Step 3: Write the failing frontend test**

In `source_code/web/src/pages/Jobs.test.tsx`:

1. Add `season: 1, episode: 5` to `ITEMS[0]` (Show A) and `season: null, episode: null` to `ITEMS[1]` (Movie X):

```typescript
const ITEMS = [
  {
    id: 1, media_item_id: 1, state: "running", phase: "transcoding", progress: 42,
    preset: null, original_size: null, output_size: null, reduction_pct: null,
    output_filename: null, error_message: null, title: "Show A",
    season: 1, episode: 5,
    created_at: "2026-05-30T09:00:00", started_at: null, finished_at: null,
  },
  {
    id: 2, media_item_id: 2, state: "failed", phase: null, progress: 0,
    preset: "H.265 NVENC 1080p", original_size: 1000000, output_size: null,
    reduction_pct: null, output_filename: null, error_message: "boom",
    title: "Movie X", season: null, episode: null,
    created_at: "2026-05-30T08:00:00", started_at: "2026-05-30T08:01:00",
    finished_at: "2026-05-30T10:30:00",
  },
];
```

2. Add a new test after `test("renders both job titles", ...)`:

```typescript
test("TV show job renders S01E05 label", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  expect(await screen.findByText(/Show A — S01E05/)).toBeInTheDocument();
});

test("movie job renders plain title without episode", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  expect(await screen.findByText(/Movie X/)).toBeInTheDocument();
  expect(screen.queryByText(/S\d\dE\d\d/)).not.toBeInTheDocument();
});
```

- [ ] **Step 4: Run to confirm failure**

```powershell
cd source_code/web
npm test -- --run Jobs
```

Expected: `TV show job renders S01E05 label` FAILS — "Show A" found but not "Show A — S01E05".

- [ ] **Step 5: Update Jobs.tsx Title column to use jobTitle()**

In `source_code/web/src/pages/Jobs.tsx`:

1. Add `jobTitle` to the badge import:
```typescript
import { Badge, jobStateVariant, jobStateLabel, jobTitle } from "../components/ui/badge";
```

2. Replace the Title `<TD>`:
```typescript
<TD>{jobTitle(job)}</TD>
```

(replaces `<TD>{job.title ?? "—"}</TD>` at line 159)

- [ ] **Step 6: Update Dashboard.tsx current-job title to use jobTitle()**

In `source_code/web/src/pages/Dashboard.tsx`:

1. Add `jobTitle` to the badge import:
```typescript
import { Badge, jobStateVariant, jobStateLabel, jobTitle } from "../components/ui/badge";
```

2. Replace the current job title span:
```typescript
<span className="text-fg font-medium truncate mr-4">
  {jobTitle(currentJob)}
</span>
```

(replaces `{currentJob.title ?? \`Job #${currentJob.id}\`}`)

Also update the Queued Jobs table title `<TD>`:
```typescript
<TD className="truncate max-w-xs">{jobTitle(job)}</TD>
```

(replaces `{job.title ?? \`Job #${job.id}\`}`)

- [ ] **Step 7: Run all frontend tests**

```powershell
cd source_code/web
npm test -- --run
```

Expected: all tests pass including the two new ones.

- [ ] **Step 8: Verify TypeScript compiles cleanly**

```powershell
cd source_code/web
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 9: Commit**

```powershell
cd ..
git add source_code/web/src/api/types.ts source_code/web/src/components/ui/badge.tsx source_code/web/src/pages/Jobs.tsx source_code/web/src/pages/Dashboard.tsx source_code/web/src/pages/Jobs.test.tsx
git commit -m "feat: show S01E05 episode label on jobs in UI

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Logging cleanup

**Files:**
- Modify: `source_code/transcoder/logging_setup.py`
- Modify: `source_code/transcoder/cli.py`
- Modify: `source_code/transcoder/api/app.py`
- Modify: `source_code/tests/test_api_jobs.py` (add `ensure_job_columns` monkeypatch)
- Modify: `source_code/tests/api_conftest.py`

- [ ] **Step 1: Write the failing test for new logging behaviour**

Create `source_code/tests/test_logging_setup.py`:

```python
import logging
import pathlib


def test_init_logging_api_creates_fixed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from transcoder.logging_setup import init_logging
    # Reset root logger so basicConfig actually runs in this test
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    logger = init_logging("api")
    log_file = tmp_path / "log" / "api.log"
    assert log_file.exists(), f"expected {log_file} to exist"
    # No dated filename pattern
    dated = list((tmp_path / "log").glob("????-??-??_??-??-??.log"))
    assert dated == [], f"unexpected dated log files: {dated}"


def test_init_logging_cli_creates_fixed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from transcoder.logging_setup import init_logging
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    logger = init_logging("cli")
    log_file = tmp_path / "log" / "cli.log"
    assert log_file.exists(), f"expected {log_file} to exist"
```

- [ ] **Step 2: Run to confirm failure**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest tests/test_logging_setup.py -v
```

Expected: FAIL — `api.log` doesn't exist (current code creates a dated file).

- [ ] **Step 3: Rewrite logging_setup.py**

Replace the entire `source_code/transcoder/logging_setup.py`:

```python
import logging
import logging.handlers
import os

from transcoder.log_buffer import log_buffer


def init_logging(component: str = "api", level: int = logging.INFO) -> logging.Logger:
    os.makedirs("log", exist_ok=True)
    fname = f"log/{component}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        fname, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    logger = logging.getLogger("transcoder")
    logger.setLevel(level)
    if log_buffer not in logger.handlers:
        log_buffer.setLevel(level)
        logger.addHandler(log_buffer)
    return logger
```

- [ ] **Step 4: Update callers**

In `source_code/transcoder/api/app.py`, change:
```python
init_logging()
```
to:
```python
init_logging("api")
```

In `source_code/transcoder/cli.py`, change:
```python
init_logging()
```
to:
```python
init_logging("cli")
```

- [ ] **Step 5: Monkeypatch ensure_job_columns in api_conftest to avoid side effects**

In `source_code/tests/api_conftest.py`, after the other monkeypatch lines (before `app = create_app(...)`), add:

```python
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "reconcile_stale_jobs", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "init_logging", lambda *a, **k: None)
```

This prevents the API fixture from touching the real DB or creating log files.

- [ ] **Step 6: Import the monkeypatched names into app_module**

Verify `source_code/transcoder/api/app.py` imports `ensure_job_columns` and `reconcile_stale_jobs` at the module level (they already are: line 8 imports `ensure_job_columns` and line 10 imports `reconcile_stale_jobs`). The `init_logging` is imported at line 7. No changes needed.

- [ ] **Step 7: Run all backend tests**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass including `test_logging_setup.py`.

- [ ] **Step 8: Commit**

```powershell
git add source_code/transcoder/logging_setup.py source_code/transcoder/cli.py source_code/transcoder/api/app.py source_code/tests/test_logging_setup.py source_code/tests/api_conftest.py
git commit -m "fix: rotating log files per component instead of dated files per run

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: DB backup before migration

**Files:**
- Modify: `source_code/transcoder/db.py`
- Modify: `source_code/transcoder/api/app.py`
- Create: `source_code/tests/test_db_backup.py`
- Modify: `source_code/tests/api_conftest.py`

- [ ] **Step 1: Write the failing test**

Create `source_code/tests/test_db_backup.py`:

```python
import pathlib
import shutil


def test_backup_db_creates_bak_file(tmp_path):
    from transcoder.db import backup_db
    db = tmp_path / "transcoder.db"
    db.write_bytes(b"SQLite data")
    backup_db(db)
    bak = tmp_path / "transcoder.db.bak"
    assert bak.exists()
    assert bak.read_bytes() == b"SQLite data"


def test_backup_db_no_error_when_file_missing(tmp_path):
    from transcoder.db import backup_db
    db = tmp_path / "transcoder.db"
    backup_db(db)  # must not raise


def test_backup_db_overwrites_previous_bak(tmp_path):
    from transcoder.db import backup_db
    db = tmp_path / "transcoder.db"
    bak = tmp_path / "transcoder.db.bak"
    bak.write_bytes(b"old backup")
    db.write_bytes(b"new data")
    backup_db(db)
    assert bak.read_bytes() == b"new data"
```

- [ ] **Step 2: Run to confirm failure**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest tests/test_db_backup.py -v
```

Expected: FAIL — `ImportError: cannot import name 'backup_db'`.

- [ ] **Step 3: Add backup_db() to db.py**

In `source_code/transcoder/db.py`, add after the `init_db` function:

```python
def backup_db(db_path=None) -> None:
    import pathlib, shutil
    p = pathlib.Path(db_path) if db_path is not None else pathlib.Path("transcoder.db")
    if p.exists():
        shutil.copy2(p, p.with_suffix(".db.bak"))
```

- [ ] **Step 4: Call backup_db in lifespan before ensure_job_columns**

In `source_code/transcoder/api/app.py`, update the import line:

```python
from transcoder.db import SessionLocal, init_db, ensure_job_columns, backup_db
```

Then in the lifespan, replace:

```python
        init_logging("api")
        init_db()
        ensure_job_columns()
```

with:

```python
        init_logging("api")
        init_db()
        backup_db()
        ensure_job_columns()
```

- [ ] **Step 5: Monkeypatch backup_db in api_conftest**

In `source_code/tests/api_conftest.py`, add to the monkeypatches block:

```python
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
```

Also add `backup_db` to the import line at the top of `api_conftest.py` — nothing to do there since we're patching via `app_module`, not by name.

- [ ] **Step 6: Run all backend tests**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add source_code/transcoder/db.py source_code/transcoder/api/app.py source_code/tests/test_db_backup.py source_code/tests/api_conftest.py
git commit -m "feat: backup transcoder.db before running column migrations

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Merge Cycle 5A → master

**Files:** none changed (git only)

- [ ] **Step 1: Run full test suite on the branch**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web test -- --run
```

Expected: all tests pass.

- [ ] **Step 2: Merge to master**

```powershell
git checkout master
git merge --no-ff cycle-5a-quick-wins -m "Merge: Cycle 5A — season/episode on jobs, log cleanup, DB backup

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git branch -d cycle-5a-quick-wins
```

- [ ] **Step 3: Verify tests on master**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

---

## Task 7: Create Cycle 5B branch + add dependencies

**Files:**
- Modify: `source_code/requirements.txt`

- [ ] **Step 1: Create branch**

```powershell
git checkout -b cycle-5b-windows-integration
```

- [ ] **Step 2: Add pystray, Pillow, winotify to requirements.txt**

Replace `source_code/requirements.txt` with:

```
requests
paramiko
tqdm
SQLAlchemy>=2.0
pydantic-settings>=2.0
pytest>=8.0
fastapi>=0.110
uvicorn[standard]>=0.29
httpx>=0.27
itsdangerous>=2.1
pystray>=0.19
Pillow>=10
winotify>=1.1
```

- [ ] **Step 3: Install new dependencies**

```powershell
cd source_code
.\.venv\Scripts\pip.exe install pystray>=0.19 "Pillow>=10" "winotify>=1.1"
```

Expected: packages install without error.

- [ ] **Step 4: Commit**

```powershell
git add source_code/requirements.txt
git commit -m "chore: add pystray, Pillow, winotify for Windows tray integration

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Tray launcher (pystray + health poll)

**Files:**
- Create: `source_code/tray.pyw`
- Create: `scripts/tray.bat`

- [ ] **Step 1: Create tray.pyw**

Create `source_code/tray.pyw`:

```python
"""Windows system tray launcher for the H.265 Transcoder service.

Run via scripts/tray.bat or:  .venv\Scripts\pythonw.exe tray.pyw
Double-click the tray icon to open the web UI; right-click for the menu.
"""
import json
import logging
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:
    import tkinter.messagebox as _mb
    _mb.showerror("Missing dependency", str(exc))
    sys.exit(1)

BASE_URL = "http://localhost:8765"
SOURCE_CODE_DIR = pathlib.Path(__file__).parent
_VENV_PY = SOURCE_CODE_DIR / ".venv" / "Scripts" / "pythonw.exe"
if not _VENV_PY.exists():
    _VENV_PY = pathlib.Path(sys.executable)

_server_proc: subprocess.Popen | None = None
_poll_state: dict = {"prev_job_id": None, "prev_queue_len": None}

log = logging.getLogger("tray")


# ── icon helpers ──────────────────────────────────────────────────────────────

def _make_icon(online: bool) -> Image.Image:
    colour = "#22c55e" if online else "#6b7280"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), fill=colour)
    return img


# ── API helpers ───────────────────────────────────────────────────────────────

def _is_up() -> bool:
    try:
        urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2)
        return True
    except Exception:
        return False


def _get_json(path: str):
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── poll thread ───────────────────────────────────────────────────────────────

def _poll(icon: pystray.Icon) -> None:
    while True:
        up = _is_up()
        icon.icon = _make_icon(up)

        if up:
            _check_job_transitions(icon)
        else:
            # Reset state so we don't misfire on reconnect.
            _poll_state["prev_job_id"] = None
            _poll_state["prev_queue_len"] = None

        time.sleep(5)


def _check_job_transitions(icon: pystray.Icon) -> None:
    status = _get_json("/api/status")
    if not status:
        return

    cur = status.get("current_job")
    queue_len = status.get("queue_length", 0)
    cur_id = cur["id"] if cur else None
    prev_id = _poll_state["prev_job_id"]
    prev_q = _poll_state["prev_queue_len"]

    # A job just finished (running job changed or worker went idle).
    if prev_id is not None and cur_id != prev_id:
        job = _get_json(f"/api/jobs/{prev_id}")
        if job:
            label = _job_label(job)
            if job["state"] == "done":
                _notify("H265 Transcoder", f"✓ Transcoded: {label}")
            elif job["state"] == "failed":
                _notify("H265 Transcoder", f"✗ Failed: {label} — see logs")

    # Queue drained to empty while nothing is running.
    if prev_q is not None and prev_q > 0 and queue_len == 0 and cur_id is None:
        _notify("H265 Transcoder", "Queue clear — all jobs done")

    _poll_state["prev_job_id"] = cur_id
    _poll_state["prev_queue_len"] = queue_len


def _job_label(job: dict) -> str:
    title = job.get("title") or f"Job #{job.get('id')}"
    s, e = job.get("season"), job.get("episode")
    if s is not None and e is not None:
        return f"{title} — S{str(s).zfill(2)}E{str(e).zfill(2)}"
    return title


def _notify(title: str, msg: str) -> None:
    try:
        from winotify import Notification, audio
        n = Notification(app_id="H265 Transcoder", title=title, msg=msg)
        n.set_audio(audio.Default, loop=False)
        n.show()
    except Exception as exc:
        log.warning("toast failed: %s", exc)


# ── menu actions ──────────────────────────────────────────────────────────────

def _open_ui(_icon, _item) -> None:
    webbrowser.open(BASE_URL)


def _start_server(_icon, _item) -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        return
    _server_proc = subprocess.Popen(
        [str(_VENV_PY), "-m", "transcoder.api"],
        cwd=str(SOURCE_CODE_DIR),
    )


def _stop_server(_icon, _item) -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
    _server_proc = None


def _exit(icon, item) -> None:
    _stop_server(icon, item)
    icon.stop()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    icon = pystray.Icon(
        name="h265transcoder",
        icon=_make_icon(False),
        title="H265 Transcoder",
        menu=pystray.Menu(
            pystray.MenuItem("Open UI", _open_ui, default=True),
            pystray.MenuItem("Start", _start_server),
            pystray.MenuItem("Stop", _stop_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", _exit),
        ),
    )
    threading.Thread(target=_poll, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create scripts/tray.bat**

Create `scripts/tray.bat`:

```batch
@echo off
REM Launch the H265 Transcoder tray icon (no console window).
REM Double-click this file or add it to your startup folder.
set ROOT=%~dp0..
start "" "%ROOT%\source_code\.venv\Scripts\pythonw.exe" "%ROOT%\source_code\tray.pyw"
```

- [ ] **Step 3: Verify imports work**

```powershell
cd source_code
.\.venv\Scripts\python.exe -c "import pystray; from PIL import Image; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```powershell
git add source_code/tray.pyw scripts/tray.bat
git commit -m "feat: Windows tray launcher with health indicator and start/stop menu

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Toast notifications (already integrated in tray.pyw)

The notification logic was built into `tray.pyw` in Task 8 (`_check_job_transitions` + `_notify`). This task verifies the logic is correct by tracing through the state machine manually and doing a smoke test.

- [ ] **Step 1: Trace the notification state machine**

Read `_check_job_transitions` in `tray.pyw` and verify:

| Scenario | Expected behaviour |
|---|---|
| `prev_job_id=None`, `cur_id=5` (new job started) | No notification (prev_id is None) |
| `prev_job_id=5`, `cur_id=None` (job 5 just finished, done) | Fetch job 5, notify "✓ Transcoded: ..." |
| `prev_job_id=5`, `cur_id=None` (job 5 just finished, failed) | Fetch job 5, notify "✗ Failed: ..." |
| `prev_id=5`, `cur_id=6` (next job started while 5 finished) | Fetch job 5, notify based on its state |
| `prev_q=3`, `queue_len=0`, `cur_id=None` | Notify "Queue clear" |
| `prev_q=0`, `queue_len=0`, `cur_id=None` | No notification (queue was already empty) |
| Server goes offline (`_is_up()=False`) | State reset; icon goes grey |

- [ ] **Step 2: Smoke-test the tray (manual, with the real server running)**

Start the API server in one terminal:
```powershell
cd source_code
.\.venv\Scripts\python.exe -m transcoder.api
```

Run the tray in another:
```powershell
cd source_code
.\.venv\Scripts\python.exe tray.pyw
```

Verify:
- Tray icon appears in the system tray
- Icon turns green within 5 seconds (server is up)
- Right-click shows Open UI, Start, Stop, Exit
- Clicking "Open UI" opens `http://localhost:8765` in a browser

Stop the server (Ctrl-C in its terminal). Within 5 seconds the tray icon turns grey.

- [ ] **Step 3: Commit**

```powershell
git add .  # only if there are any edits from the trace/test
git commit -m "feat: toast notifications on job completion and queue drain

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>" --allow-empty
```

(Use `--allow-empty` only if no files changed; omit if you made edits.)

---

## Task 10: Merge Cycle 5B → master

**Files:** none changed (git only)

- [ ] **Step 1: Run full backend test suite**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Merge to master**

```powershell
git checkout master
git merge --no-ff cycle-5b-windows-integration -m "Merge: Cycle 5B — Windows tray launcher + toast notifications

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git branch -d cycle-5b-windows-integration
```

- [ ] **Step 3: Verify tests on master**

```powershell
cd source_code
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.
