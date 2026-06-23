# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Helper scripts (Windows):** `scripts/build.bat` (venv + deps + web build), `scripts/run.bat` (start the service), `scripts/clean.bat` (remove venv/node_modules/dist), `scripts/install-service.bat` (run at logon), `scripts/uninstall-service.bat` (stop + remove scheduled task), `scripts/tray.bat` (system tray launcher). See `scripts/README.md`.

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
`POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`, `POST /api/jobs/delete` (bulk-delete terminal-state jobs by id list), `GET /api/jobs/{id}/logs`,
`GET /api/exclusions`, `GET /api/status`, `GET /api/stream` (SSE), `GET /api/logs`,
`POST /api/library/{id}/enqueue`,
`POST /api/webhook/{source}` (`source` = `sonarr`|`radarr`; open route that
self-authenticates via HTTP Basic against `webhook_username`/`webhook_password_hash`
settings — Sonarr/Radarr call it on import to trigger a targeted discover +
enqueue of just that title; non-`Download` events are ack'd and ignored). A
continuous background worker drains the job queue automatically while the server
runs.

**Web UI (Cycle 3):** a React SPA (Vite + Tailwind + shadcn-style primitives) in `source_code/web/`, served by FastAPI behind a single-password login. Requires `APP_PASSWORD` + `SECRET_KEY` in `.env`.
```bash
# Dev (hot reload): two processes
cd source_code && python -m transcoder.api          # API on :8765
cd source_code/web && npm install && npm run dev     # UI on :5173, proxies /api -> :8765
# Prod: build once, FastAPI serves UI + API on :8765
cd source_code/web && npm run build                  # -> web/dist
cd source_code && python -m transcoder.api           # open http://<host>:8765, log in
```
Screens: Dashboard (live status/progress via SSE, plus a "space saved" stat — absolute bytes + % reclaimed across completed jobs, served on `GET /api/status` as `savings`), Library (filter/enqueue/exclude/scan), Jobs (cancel/retry), Exclusions, Logs (live activity), Settings (connections, scheduler, encoder, security, and a Webhooks section that shows the two `/api/webhook/{source}` URLs and sets the Basic-auth credentials Sonarr/Radarr use). Frontend tests: `cd source_code/web && npm test`.

Activity logging: the `transcoder` logger feeds an in-memory ring buffer (last 500 records); `GET /api/logs?after=<seq>` returns new lines incrementally and the Logs page polls it (~2s).

**Windows batch shortcut:** `source_code/run.bat`

## Testing

Use TDD: write or update tests describing the desired behavior **before** writing the
implementation, then code until green. Run the full suite before committing — don't
declare a fix or feature done until tests are green.

- **Backend (pytest):** `cd source_code && python -m pytest` (config in `pytest.ini`;
  tests live in `source_code/tests/`, named `test_*.py`).
- **Frontend (Vitest):** `cd source_code/web && npm test`. This runs `tsc -b`
  (typecheck) before Vitest, so type errors fail the suite — Vitest alone does not
  typecheck, and the production build (`npm run build`) runs the same `tsc -b`. Use
  `npm run typecheck` to typecheck without running tests.

For bug fixes, first add a failing test that reproduces the defect, then fix it — this
catches the *real* root cause rather than a surface symptom, and guards against the
regression coming back.

## Git Workflow

Standard end-to-end flow when shipping a feature or fix:

1. Verify the full test suite passes (backend + frontend, see ## Testing).
2. Commit with a clean, conventional message.
3. Merge to `master`.
4. Push.
5. Delete the feature branch.

Never bypass hooks (`--no-verify`) or signing unless explicitly asked. The `/ship` skill
codifies this flow.

## Windows Notes

This is primarily a Windows worker/server project; the shell is PowerShell.

- **Avoid PowerShell here-strings for commit messages** — they have injected a stray `@`
  into commit messages, forcing amend + force-push cleanups. Prefer a plain single-line
  `-m` message, or write the message to a file and use `git commit -F <file>`.
- Use Windows-safe quoting for `schtasks` and SQL commands run through the shell; the
  shell has mangled these flags before. When in doubt, run them natively rather than
  piping complex strings.

## UI / Screenshots

Before opening pages in a browser for screenshots, start a real local HTTP server and
verify it responds first — do **not** use `file://` URLs or assume the FastAPI server is
already running. For the web UI, build (`npm run build`) and serve via FastAPI, or run the
Vite dev server (`npm run dev`). For UI tweaks, work from an annotated screenshot or the
exact element/selector to avoid mis-identifying the target.

## Architecture

This is a video transcoding pipeline that converts media to H.265/HEVC. It queries Sonarr/Radarr APIs to find non-H.265 files, downloads them via SFTP, transcodes with HandBrake CLI, and uploads the result back for automatic re-import.

**Flow:** Sonarr/Radarr API → `discovery` upserts `media_item` rows (eligibility = needs_transcode if non-H.265 ≥1080p) → `queue` creates `job` rows → `worker` drains jobs one at a time: SFTP download → HandBrakeCLI (with live progress) → if smaller: SFTP upload + manual import trigger; if larger: add `exclusion` row

**Key modules (`source_code/transcoder/`):**
- `cli.py` — thin entry point; `build_parser()` + `main()` dispatch the `scan`/`run`/`queue` commands
- `config.py` — pydantic-settings loaded from `.env` (gitignored; see `.env.example`)
- `db.py` — SQLAlchemy engine/session/`Base`/`init_db`/`backup_db` (copies `transcoder.db` → `.db.bak` before migrations)
- `models.py` — ORM models: `MediaItem`, `Job`, `Exclusion`, `Setting` + exclusion-key helpers
- `repo.py` — shared data-access helpers (upsert, settings, exclusions); callers own commits
- `migrate.py` — one-time import of legacy CSV/timestamp state into the DB
- `engine/eligibility.py` — pure `compute_eligibility()` rule
- `engine/discovery.py` — scans Sonarr/Radarr, upserts `media_item`s, advances the watermark
- `engine/queue.py` — turns eligible items into `queued` jobs (deduped)
- `engine/worker.py` — serial worker: download → transcode → replace-or-exclude → cleanup
- `api/` — FastAPI service (Cycle 2): `app.py` (factory + lifespan), `deps.py`, `schemas.py`, `state.py` (worker controller + scan status singletons), `routers/` (library, scan, jobs, exclusions, stream/status), `auth.py` (single-password session login, `require_auth`). `worker_controller.py` runs the continuous background transcode worker (cancellable).
- `web/` — React SPA (Cycle 3, Vite + Tailwind + shadcn-style primitives in `src/components/ui/`): `api/` client+types, `hooks/` (TanStack Query + SSE), `pages/` (Dashboard/Library/Jobs/Exclusions/Login), `auth/` (AuthGate). Built to `web/dist`, served by FastAPI. Data tables (Library/Jobs/Exclusions) use a shared `components/ui/data-table.tsx` (TanStack Table) that renders through the Tailwind `Table` primitives — columns are click-to-sort with `aria-sort`; Jobs defaults to the "When" column (`finished_at ?? started_at ?? created_at`) descending.
- `sonarr_client.py` / `radarr_client.py` — API clients; `is_h265_encoded()` checks `customFormats` for "x265"
- `convert.py` — HandBrake CLI wrapper; `parse_handbrake_progress()` + `progress_cb`; returns `(output_path, excluded_flag)`
- `sftp_client.py` — upload/download via Paramiko with tqdm progress bars
- `history.py` — `_parse_iso_z()` ISO-8601 parsing (used by discovery for the watermark)
- `logging_setup.py` — leveled logging to console + rotating file (`log/api.log` for the server, `log/cli.log` for the CLI; 5 MB / 3 backups)
- `tray.pyw` — Windows system tray launcher (pystray + Pillow): green/grey health icon, start/stop/open-UI menu, toast notifications on job done/failed/queue-clear (winotify); run via `scripts/tray.bat`

**State** lives in a SQLite database (`source_code/transcoder.db`): `media_item`, `job`,
`exclusion`, `setting` tables. Legacy `excluded_*.csv` / `last_history_timestamp.txt` are
auto-imported on first run and renamed `*.migrated`. Config is loaded from `source_code/.env`
(see `.env.example`); the old hardcoded `config.py` is gitignored.

## External Dependencies

- **HandBrake CLI**: path configured via `HANDBRAKE_CLI` (e.g. `C:\path\to\HandBrakeCLI.exe`)
  - Presets: `"H.265 NVENC 1080p"` and `"H.265 NVENC 2160p 4K"`
- **Sonarr**: `http://<sonarr-host>:<port>` (e.g. `http://localhost:8989`)
- **Radarr**: `http://<radarr-host>:<port>` (e.g. `http://localhost:7878`)
- **SFTP**: `<sftp-host>:22`

All endpoints and credentials are configured via `.env` (see `.env.example`); nothing is hardcoded.
