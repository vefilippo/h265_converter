# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Helper scripts (Windows):** `scripts/build.bat` (venv + deps + web build), `scripts/run.bat` (start the service), `scripts/clean.bat` (remove venv/node_modules/dist), `scripts/install-service.bat` (run at logon). See `scripts/README.md`.

**Setup:**
```bash
cd source_code
python -m pip install -r requirements.txt
```

**Run:**
```bash
cd source_code
python -m transcoder.cli <command> [app] [scope] [--show "Title"] [--movie "Title"]
# command: scan | run | queue
# app: all | sonarr | radarr (default all)
# scope: all | new (default all)
```

Examples:
```bash
python -m transcoder.cli run all                    # Discover, enqueue, transcode everything
python -m transcoder.cli run sonarr new             # New TV episodes only
python -m transcoder.cli scan radarr all            # Discover movies only (no transcoding)
python -m transcoder.cli run sonarr all --show "Breaking Bad"
python -m transcoder.cli run radarr all --movie "Inception"
python -m transcoder.cli queue                      # List job states
```

**Serve (API, Cycle 2):**
```bash
cd source_code
python -m transcoder.api        # FastAPI + uvicorn on API_HOST:API_PORT (default 0.0.0.0:8765)
```
Key endpoints: `GET /api/health`, `GET /api/library`, `GET /api/library/stats`,
`POST /api/scan`, `GET /api/scan/status`, `POST /api/enqueue`, `GET /api/jobs`,
`POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`,
`GET /api/exclusions`, `GET /api/status`, `GET /api/stream` (SSE). A continuous
background worker drains the job queue automatically while the server runs.

**Web UI (Cycle 3):** a React SPA (Vite + Tailwind + shadcn-style primitives) in `source_code/web/`, served by FastAPI behind a single-password login. Requires `APP_PASSWORD` + `SECRET_KEY` in `.env`.
```bash
# Dev (hot reload): two processes
cd source_code && python -m transcoder.api          # API on :8765
cd source_code/web && npm install && npm run dev     # UI on :5173, proxies /api -> :8765
# Prod: build once, FastAPI serves UI + API on :8765
cd source_code/web && npm run build                  # -> web/dist
cd source_code && python -m transcoder.api           # open http://<host>:8765, log in
```
Screens: Dashboard (live status/progress via SSE), Library (filter/enqueue/exclude/scan), Jobs (cancel/retry), Exclusions. Frontend tests: `cd source_code/web && npm test`.

**Windows batch shortcut:** `source_code/run.bat`

## Architecture

This is a video transcoding pipeline that converts media to H.265/HEVC. It queries Sonarr/Radarr APIs to find non-H.265 files, downloads them via SFTP, transcodes with HandBrake CLI, and uploads the result back for automatic re-import.

**Flow:** Sonarr/Radarr API → `discovery` upserts `media_item` rows (eligibility = needs_transcode if non-H.265 ≥1080p) → `queue` creates `job` rows → `worker` drains jobs one at a time: SFTP download → HandBrakeCLI (with live progress) → if smaller: SFTP upload + manual import trigger; if larger: add `exclusion` row

**Key modules (`source_code/transcoder/`):**
- `cli.py` — thin entry point; `build_parser()` + `main()` dispatch the `scan`/`run`/`queue` commands
- `config.py` — pydantic-settings loaded from `.env` (gitignored; see `.env.example`)
- `db.py` — SQLAlchemy engine/session/`Base`/`init_db`
- `models.py` — ORM models: `MediaItem`, `Job`, `Exclusion`, `Setting` + exclusion-key helpers
- `repo.py` — shared data-access helpers (upsert, settings, exclusions); callers own commits
- `migrate.py` — one-time import of legacy CSV/timestamp state into the DB
- `engine/eligibility.py` — pure `compute_eligibility()` rule
- `engine/discovery.py` — scans Sonarr/Radarr, upserts `media_item`s, advances the watermark
- `engine/queue.py` — turns eligible items into `queued` jobs (deduped)
- `engine/worker.py` — serial worker: download → transcode → replace-or-exclude → cleanup
- `api/` — FastAPI service (Cycle 2): `app.py` (factory + lifespan), `deps.py`, `schemas.py`, `state.py` (worker controller + scan status singletons), `routers/` (library, scan, jobs, exclusions, stream/status), `auth.py` (single-password session login, `require_auth`). `worker_controller.py` runs the continuous background transcode worker (cancellable).
- `web/` — React SPA (Cycle 3, Vite + Tailwind + shadcn-style primitives in `src/components/ui/`): `api/` client+types, `hooks/` (TanStack Query + SSE), `pages/` (Dashboard/Library/Jobs/Exclusions/Login), `auth/` (AuthGate). Built to `web/dist`, served by FastAPI.
- `sonarr_client.py` / `radarr_client.py` — API clients; `is_h265_encoded()` checks `customFormats` for "x265"
- `convert.py` — HandBrake CLI wrapper; `parse_handbrake_progress()` + `progress_cb`; returns `(output_path, excluded_flag)`
- `sftp_client.py` — upload/download via Paramiko with tqdm progress bars
- `history.py` — `_parse_iso_z()` ISO-8601 parsing (used by discovery for the watermark)
- `logging_setup.py` — real leveled logging to console + `source_code/log/`

**State** lives in a SQLite database (`source_code/transcoder.db`): `media_item`, `job`,
`exclusion`, `setting` tables. Legacy `excluded_*.csv` / `last_history_timestamp.txt` are
auto-imported on first run and renamed `*.migrated`. Config is loaded from `source_code/.env`
(see `.env.example`); the old hardcoded `config.py` is gitignored.

## External Dependencies

- **HandBrake CLI**: `C:\Users\vefil\Documents\HandBrakeCLI\HandBrakeCLI.exe`
  - Presets: `"H.265 NVENC 1080p"` and `"H.265 NVENC 2160p 4K"`
- **Sonarr**: `http://your-arr-host:8989`
- **Radarr**: `http://your-arr-host:7878`
- **SFTP**: `192.168.x.x:22`

All credentials are hardcoded in `config.py`.
