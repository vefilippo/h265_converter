# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

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
