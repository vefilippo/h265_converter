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
python -m transcoder.cli <app> [scope] [--show "Title"] [--movie "Title"]
# app: all | sonarr | radarr
# scope: all | new (default: all)
```

Examples:
```bash
python -m transcoder.cli all              # Process all content
python -m transcoder.cli sonarr new       # New TV episodes only
python -m transcoder.cli sonarr all --show "Breaking Bad"
python -m transcoder.cli radarr all --movie "Inception"
```

**Windows batch shortcut:** `source_code/run.bat`

## Architecture

This is a video transcoding pipeline that converts media to H.265/HEVC. It queries Sonarr/Radarr APIs to find non-H.265 files, downloads them via SFTP, transcodes with HandBrake CLI, and uploads the result back for automatic re-import.

**Flow:** Sonarr/Radarr API → filter non-H.265 ≥1080p → SFTP download → HandBrakeCLI → if smaller: SFTP upload + manual import trigger; if larger: add to exclusion CSV

**Key modules (`source_code/transcoder/`):**
- `cli.py` — entry point; `handle_sonarr()` and `handle_radarr()` orchestrate the full pipeline
- `config.py` — all settings hardcoded here (API keys, SFTP creds, paths, HandBrake presets)
- `sonarr_client.py` / `radarr_client.py` — API clients; `is_h265_encoded()` checks `customFormats` for "x265"
- `convert.py` — HandBrake CLI subprocess wrapper; returns `(output_path, excluded_flag)`
- `sftp_client.py` — upload/download via Paramiko with tqdm progress bars
- `history.py` — ISO-8601 timestamp watermark (`last_history_timestamp.txt`) for incremental runs
- `exclusion.py` — CSV-based blacklists (`excluded_episodes.csv`, `excluded_movies.csv`)
- `logging_setup.py` — redirects `print()` to `logging.info()`; logs written to `source_code/log/`

**State files** (all in `source_code/`):
- `last_history_timestamp.txt` — watermark for `scope=new`; first run processes everything
- `excluded_episodes.csv` / `excluded_movies.csv` — items skipped because H.265 output was larger

## External Dependencies

- **HandBrake CLI**: `C:\Users\vefil\Documents\HandBrakeCLI\HandBrakeCLI.exe`
  - Presets: `"H.265 NVENC 1080p"` and `"H.265 NVENC 2160p 4K"`
- **Sonarr**: `http://your-arr-host:8989`
- **Radarr**: `http://your-arr-host:7878`
- **SFTP**: `192.168.x.x:22`

All credentials are hardcoded in `config.py`.
