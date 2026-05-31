# Design: Quick Wins + Windows Integration

**Date:** 2026-05-31  
**Branch base:** master (after merging job-phases-and-logs)

---

## Overview

Two sequential cycles of improvement to the H.265 transcoder service.

**Cycle 5A — Quick Wins:** three small, independent improvements to the existing web service.  
**Cycle 5B — Windows Integration:** a separate tray launcher process with health indicator and toast notifications.  
**Cycle 5C — Interactive Cleanup:** codebase cleanup done interactively with the user (no spec; out of scope here).

---

## Prerequisite

Merge branch `job-phases-and-logs` → `master` (local `--no-ff` merge) before starting either cycle.

---

## Cycle 5A — Quick Wins

### #3 — Job season/episode in the Jobs view

**Problem:** The `Jobs` page and `Dashboard` current-job card show the title but not season/episode, making TV shows ambiguous (e.g. "Breaking Bad" with no episode info).

**Change:**
- `schemas.py` — add `season: int | None = None` and `episode: int | None = None` to `JobOut`
- `routers/jobs.py` — populate both fields in `_to_out()` from `job.media_item`
- `web/src/api/types.ts` — add `season: number | null` and `episode: number | null` to `Job`
- `web/src/pages/Jobs.tsx` + `Dashboard.tsx` — render as `"Show Title — S01E05"` for TV (season+episode present) or plain `"Title"` for movies

### #4 — Logging cleanup

**Problem:** `logging_setup.py` creates a new dated log file on every process start. Hundreds of files accumulate in `source_code/log/`, many empty (from test runs, rapid restarts).

**Fix:** Replace the dated-filename pattern with two fixed rotating files:

| Component | File |
|-----------|------|
| API server (`python -m transcoder.api`) | `log/api.log` |
| CLI (`python -m transcoder.cli`) | `log/cli.log` |

`init_logging(component: str = "api")` selects the filename. Handler: `RotatingFileHandler(maxBytes=5*1024*1024, backupCount=3)` — old runs append, rotate at 5 MB, keep 3 backups. The `StreamHandler` (console) remains for both.

Tests should not call `init_logging()` at all (they already don't in most cases; pytest captures logging natively). Existing dated files in `log/` are left as-is (not deleted automatically).

### #6 — DB backup before migration

**Problem:** `ensure_job_columns()` runs ALTER TABLE statements on startup. A bad migration could corrupt the DB with no recovery path.

**Fix:** In `api/app.py` lifespan, before calling `ensure_job_columns()`:

```python
import shutil, pathlib
db_path = pathlib.Path("transcoder.db")
if db_path.exists():
    shutil.copy2(db_path, db_path.with_suffix(".db.bak"))
```

Single `.bak` file (overwritten on each startup). Sufficient for the one-shot migration scenario; no versioned history needed.

---

## Cycle 5B — Windows Integration

### Architecture

All Windows-specific code lives in a separate launcher process (`tray.pyw`). The API server (`transcoder/api/`) remains platform-neutral — no `pystray`, `winotify`, or Windows APIs imported there.

```
[tray.pyw]  ←── subprocess ──→  [python -m transcoder.api]
     │                                       │
  pystray                              FastAPI + worker
  winotify                             (unchanged)
  polls /api/*
```

### #1 — System tray launcher

**File:** `source_code/tray.pyw` (`.pyw` = no console window on Windows)

**Dependencies (add to `requirements.txt`):** `pystray>=0.19`, `Pillow>=10`

**Icon:** Generated at runtime via `Pillow` — a 64×64 image, solid circle, green when server reachable, grey when not. No external image file.

**Menu (right-click):**
- **Open UI** — `webbrowser.open("http://localhost:8765")`
- **Start** — launch `subprocess.Popen([venv_python, "-m", "transcoder.api"], cwd=source_code_dir)`
- **Stop** — terminate the subprocess
- *(separator)*
- **Exit** — stop server (if running) + exit tray

**Health poll:** every 5 seconds, `GET http://localhost:8765/api/health`. Updates icon colour and enables/disables menu items accordingly.

**Venv python path:** resolved relative to `tray.pyw` location: `../source_code/.venv/Scripts/pythonw.exe` (falls back to `python`). Port is hardcoded to `8765`; can later be read from `.env`.

**Launcher:** `scripts/tray.bat` — activates venv, runs `start pythonw source_code\tray.pyw` (detached, no console).

### #2 — Toast notifications

**Dependency (add to `requirements.txt`):** `winotify>=1.1`

**Source:** the tray health-poll thread (every 5s) also fetches `GET /api/status`. It maintains a small local state dict: `{last_job_id, last_job_state, queue_was_nonempty}`.

**Notification triggers:**

| Condition | Toast |
|-----------|-------|
| Job transitions to `done` | `"✓ Transcoded: Title S01E05"` |
| Job transitions to `failed` | `"✗ Failed: Title — see logs"` |
| Queue length drops from >0 to 0 (after ≥1 job ran this session) | `"Queue clear — all jobs done"` |

Notifications are fire-and-forget (`winotify.Notification(...).show()`). No notification is sent if the tray just started and the queue was already empty.

---

## Out of scope

- Config editor UI (deferred to a later cycle)
- Cross-platform notifications (Windows only)
- Persistent notification history
- Multiple simultaneous server instances
- Cycle 5C interactive cleanup (done interactively with user, no spec)
