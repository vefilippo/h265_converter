# h265_converter

Automated H.265/HEVC transcoding pipeline for your media library. Integrates with **Sonarr** (TV) and **Radarr** (movies) to find non-H.265 files, downloads them over SFTP, transcodes with **HandBrakeCLI**, and uploads the result back for automatic re-import. Files that end up *larger* after transcoding are excluded automatically.

<!-- screenshot -->

## Features

- **Web UI** — Dashboard with live progress (SSE), Library (filter / enqueue / exclude), Jobs (cancel / retry), live Logs, and Settings. The Library, Jobs, and Exclusions tables are sortable (click a column header); Jobs defaults to most-recent-first.
- **Runtime configuration** — edit Sonarr/Radarr URLs + API keys, SFTP credentials, and the HandBrake CLI path/preset from the Settings page; no restart required.
- **Scheduler** — cron-based auto-runs (APScheduler) with a run-at-startup toggle.
- **Webhook triggers** — Sonarr/Radarr call the app the moment a file is imported, so it's discovered and queued for transcoding instantly instead of waiting for the next scan.
- **Authentication** — single-password login, bcrypt-hashed and stored in the DB after first login, with a session cookie.
- **Windows tray app** — green/grey health dot, start/stop the server, and toast notifications on job done / failed / queue cleared.
- **Logging** — daily-rotating files in `log/` with a 30-day archive and a consistent format across all components.
- **CLI** — headless `scan` / `run` / `queue` commands for scripted use.

## Requirements

- Python 3.11+
- Node.js 18+
- HandBrakeCLI (path set in `.env`)
- A Sonarr and/or Radarr instance
- SFTP access to the media storage

## Quick start

```bash
# 1. Copy and fill in the config
cp source_code/.env.example source_code/.env

# 2. Build (venv + Python deps + React UI)
scripts\build.bat

# 3. Run
scripts\run.bat          # API + web UI on http://localhost:8765
# or
scripts\tray.bat         # Windows tray launcher (starts the server automatically)
```

Then open <http://localhost:8765> and log in with `APP_PASSWORD`.

## Configuration

All config lives in `source_code/.env` (gitignored). Copy `source_code/.env.example` and fill it in. Credentials can also be overridden at runtime from the Settings page — they are never committed.

| Variable | Description |
| --- | --- |
| `APP_PASSWORD` | Web UI login password (bcrypt-hashed into the DB on first login) |
| `SECRET_KEY` | Secret used to sign session cookies |
| `API_HOST` / `API_PORT` | Bind address for the server (default `0.0.0.0:8765`) |
| `SONARR_URL` / `SONARR_API_KEY` | Sonarr instance + API key |
| `RADARR_URL` / `RADARR_API_KEY` | Radarr instance + API key |
| `SFTP_HOST` / `SFTP_PORT` | Media storage SFTP server |
| `SFTP_USERNAME` / `SFTP_PASSWORD` | SFTP credentials |
| `HANDBRAKE_CLI` | Full path to `HandBrakeCLI.exe` |
| `PRESET_1080` | HandBrake preset name for 1080p sources |
| `PRESET_4K` | HandBrake preset name for 4K/2160p sources |

> The app password is bcrypt-hashed and stored in the DB after first login; raw credentials stay in `.env` only.

## Webhooks (instant triggering)

By default new media is found by a scan (manual, scheduled, or the watermark "new" walk). To transcode the moment something is imported, point Sonarr/Radarr at the app's webhook:

1. In the web UI, open **Settings → Webhooks**, set a username and password, and copy the two URLs shown (`http://<this-host>:8765/api/webhook/sonarr` and `…/radarr`).
2. In Sonarr/Radarr, go to **Settings → Connect → + → Webhook**:
   - **URL** — the matching URL from step 1.
   - **Method** — `POST`.
   - **Username / Password** — the credentials from step 1 (sent as HTTP Basic auth).
   - **Triggers** — enable **On Import** and **On Import Upgrade**.

On import the app authenticates the call, then runs a *targeted* discover + enqueue for just that series/movie and wakes the worker. Other events (Test, Grab, Rename) are acknowledged and ignored. Re-imported H.265 files are not re-queued, so there's no feedback loop. The host must be reachable from the Sonarr/Radarr machine.

## Scripts

All scripts live in `scripts/` (Windows batch):

| Script | Description |
| --- | --- |
| `build.bat` | Create the venv, install deps, build the React UI |
| `run.bat` | Start the FastAPI service (serves built UI + API on :8765) |
| `tray.bat` | Launch the system tray app |
| `install-service.bat` | Register a scheduled task to start at logon |
| `uninstall-service.bat` | Remove the scheduled task |
| `clean.bat` | Remove `venv`, `node_modules`, and `dist` |

## CLI

For scripted / headless use:

```bash
cd source_code
python -m transcoder.cli run all          # discover + transcode everything
python -m transcoder.cli run sonarr new   # new TV episodes only
python -m transcoder.cli scan radarr      # discover only, no transcoding
python -m transcoder.cli queue            # list job states
```

## Development

```bash
# Backend (API on :8765)
cd source_code && python -m transcoder.api

# Frontend (hot reload — UI on :5173, proxies /api -> :8765)
cd source_code/web && npm run dev

# Tests
cd source_code && python -m pytest
cd source_code/web && npm test
```

## Architecture

```
Sonarr/Radarr API
      │  discovery upserts media_item rows
      ▼
   queue  ──>  creates job rows
      │
      ▼
   worker  ──>  SFTP download → HandBrakeCLI → SFTP upload + manual import trigger
```

- **Backend** — Python 3.11+, FastAPI, SQLAlchemy, APScheduler, Paramiko (SFTP), pydantic-settings.
- **Frontend** — React 18, Vite, Tailwind CSS, TanStack Query 5, TanStack Table 8, cronstrue.
- **Windows** — pystray, winotify, Pillow.
- **State** — SQLite (WAL mode); `media_item`, `job`, `exclusion`, and `setting` tables.

### Key paths

| Path | Purpose |
| --- | --- |
| `source_code/.env.example` | Template for all required config |
| `source_code/transcoder/` | Python backend |
| `source_code/web/` | React frontend |
| `source_code/tray.pyw` | Windows tray launcher |
| `scripts/` | Windows batch scripts |
| `log/` | Daily-rotating logs (gitignored); 30-day archive in `log/archive/` |

## License

Released under the [MIT License](LICENSE).
