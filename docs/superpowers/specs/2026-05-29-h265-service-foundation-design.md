# H.265 Converter Service — Cycle 1: Foundation (Design Spec)

**Date:** 2026-05-29
**Status:** Approved (design)
**Scope:** Cycle 1 of 4 — the headless engine + persistent state foundation. No web layer yet.

---

## 1. Context & Goal

Today the project is a personal Python script that queries Sonarr/Radarr, finds non‑H.265 files ≥1080p, downloads them via SFTP, transcodes with HandBrake CLI, and (if the result is smaller) uploads + triggers a re‑import; otherwise it blacklists the item in a CSV.

The end goal is a **web-accessible service** to track and execute conversions. That is too large for one spec, so it is decomposed into four build cycles (see Appendix A). **This spec covers Cycle 1 only.**

Cycle 1 rebuilds the engine on a foundation a service needs: a persistent **job/state model** in SQLite, **secrets out of source**, **real logging**, and **captured transcode progress** — while preserving today's behavior exactly. It remains runnable and testable from the CLI, with no web layer.

### Fixed constraints (decided during brainstorming)
- **Single Windows machine.** The worker is pinned here because HandBrakeCLI + the NVENC GPU live on this box.
- **One GPU → serial queue.** Transcodes run one at a time. No Redis/Celery/parallel fleet.
- **Single local user on the LAN.** No multi-user roles. (Auth lands in a later cycle.)
- **Replace flow stays fully automatic.** Smaller output is uploaded + imported automatically, replacing the original; larger output is excluded. Job records capture what happened for auditing.

### Non-goals for Cycle 1
- No HTTP API, no web UI (Cycles 2–3).
- No scheduling, notifications, or run-as-service (Cycle 4).
- No change to *what* gets transcoded or *how* — only *how state is tracked*.

---

## 2. Data Model (SQLite)

A single SQLite file replaces `excluded_episodes.csv`, `excluded_movies.csv`, and `last_history_timestamp.txt`. Tables managed via SQLAlchemy models.

### `media_item`
One row per discovered episode or movie.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `source` | str | `sonarr` \| `radarr` |
| `external_id` | str | Sonarr: `episodeFileId`; Radarr: `movieFileId`. Stable handle to the file. |
| `series_id` / `movie_id` | int? | Parent id for import calls. |
| `title` | str | Series or movie title. |
| `season` / `episode` | int? | TV only (null for movies). |
| `year` | int? | Movie only. |
| `remote_path` | str | Path as reported by Sonarr/Radarr. |
| `codec` | str? | From mediaInfo / custom formats. |
| `resolution` | int | e.g. `1080`, `2160`. |
| `quality` | str? | e.g. `HDTV-1080p`. |
| `languages` | str? | e.g. `ENG-ITA`. |
| `size_bytes` | int? | Original file size if known. |
| `is_h265` | bool | |
| `eligibility` | str | Derived: `needs_transcode` \| `already_h265` \| `below_1080p` \| `excluded`. |
| `last_scanned_at` | datetime | |

**Uniqueness:** `(source, external_id)`. Re-scans **upsert** (update metadata, refresh `last_scanned_at`) rather than duplicate.

### `job`
One row per transcode attempt on a `media_item` (fine-grained: one item = one job).

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `media_item_id` | int FK → media_item | |
| `state` | str | `queued` \| `running` \| `done` \| `failed` \| `skipped_larger` \| `cancelled` |
| `progress` | int | 0–100, updated live during transcode. |
| `preset` | str | HandBrake preset used. |
| `created_at` / `started_at` / `finished_at` | datetime? | |
| `original_size` / `output_size` | int? | bytes |
| `reduction_pct` | float? | |
| `output_filename` | str? | |
| `error_message` | str? | populated on `failed`. |
| `log_excerpt` | text? | tail of HandBrake/worker output for later UI display. |

### `exclusion`
Replaces the two CSVs.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `source` | str | `sonarr` \| `radarr` |
| `key` | str | TV: `"<title>|<season>|<episode>"`; Movie: `"<title>"`. |
| `reason` | str | `output_larger` \| `manual` |
| `created_at` | datetime | |

**Uniqueness:** `(source, key)`.

### `setting`
Key/value store. Holds `sonarr_watermark` and `radarr_watermark` (ISO‑8601), replacing `last_history_timestamp.txt`. Extensible for future cycles.

### One-time migration (on first boot)
If the legacy files exist, import them into the DB, then leave the originals in place (renamed `*.migrated`) for safety:
- `excluded_episodes.csv` / `excluded_movies.csv` → `exclusion` rows (`reason=output_larger`).
- `last_history_timestamp.txt` → `setting['sonarr_watermark']` (Sonarr-only, matching today).

---

## 3. Engine Refactor (module boundaries)

The two monolithic functions `handle_sonarr` / `handle_radarr` are split into composable units under `transcoder/engine/`. Existing clients are reused with minimal change.

### `engine/discovery.py`
- **Does:** Scans Sonarr/Radarr (honoring `--show`/`--movie` filters), upserts `media_item` rows, computes `eligibility`, advances the watermark.
- **Scope handling (preserved from today):** Sonarr honors `scope=new` via the history watermark; **Radarr always scans all movies** (current code ignores `scope` for Radarr). A Radarr watermark is deferred to a later cycle to avoid behavior drift now.
- **Depends on:** `SonarrClient`, `RadarrClient`, DB session.
- **Output:** count of items discovered / eligible. No transcoding.

### `engine/queue.py`
- **Does:** Selects `eligibility == needs_transcode` items not already excluded and not already having a `queued`/`running` job, and creates `queued` jobs. Idempotent (safe to call repeatedly).
- **Depends on:** DB session.

### `engine/worker.py`
- **Does:** Drains the queue **one job at a time**. Per job: mark `running` → SFTP download → `convert_with_handbrake(..., progress_cb)` (updates `job.progress`) → decide:
  - output smaller → SFTP upload + `manual_import_one` → mark `done` (record sizes/reduction).
  - output larger → add `exclusion(reason=output_larger)`, set item `eligibility=excluded`, mark job `skipped_larger`.
  - HandBrake/transfer error → mark `failed` with `error_message`.
  - Always clean up temp files.
- **Depends on:** `sftp_client`, `convert`, the relevant API client (for import), DB session.
- **Concurrency:** single worker, serial. (A DB-level guard prevents two workers grabbing the same job, in case Cycle 2 runs it as a background thread.)

### Changes to existing modules
- **`convert.py`:** add a `progress_cb: Callable[[int], None]` parameter; call it from the existing `Encoding NN%` regex (replacing the dead `1 == 1`). Behavior otherwise unchanged.
- **`sonarr_client.py` / `radarr_client.py` / `sftp_client.py`:** unchanged (consumed by the engine).
- **`history.py` / `exclusion.py`:** logic moves into the DB layer; modules become thin shims or are removed once callers are migrated. The CSV/file readers are reused once, by the migration step.

---

## 4. Config & Secrets

- Introduce **`pydantic-settings`**. `config.py` reads from a **`.env`** file (and process env), with the dataclass constants becoming typed settings fields.
- `.env` holds: Sonarr/Radarr URLs + API keys, SFTP host/port/user/password, HandBrake path, presets, folder mappings, release tag, DB path.
- Ship a committed **`.env.example`** (no secrets) and add `.env` to `.gitignore`.
- **Security note:** the credentials currently hardcoded in `config.py` (including the SFTP password) are considered compromised and should be **rotated** as part of this cycle.

---

## 5. Logging

- Remove the `builtins.print = logging.info` monkeypatch.
- Use the stdlib `logging` module with proper **levels** (info/warning/error). Existing emoji `print` calls are converted to appropriate-level log calls.
- Keep file + console handlers (as today), timestamped log file under `log/`.
- The worker additionally captures a **per-job log tail** into `job.log_excerpt` for the future UI.

---

## 6. CLI (preserved for testing)

`python -m transcoder.cli` keeps working, now backed by the engine + DB:

| Command | Behavior |
|---|---|
| `scan <app> [scope] [--show/--movie]` | Run discovery; populate/refresh `media_item`s. |
| `run <app> [scope] [--show/--movie]` | Discovery → enqueue → drain queue (equivalent to today's end-to-end run). |
| `queue` | List current jobs and their states (text). |

`<app>` = `all|sonarr|radarr`, `scope` = `all|new` (default `all`) — same semantics as today. This lets us verify Cycle 1 fully before any web layer exists.

---

## 7. Testing (TDD)

`pytest`, with HTTP/SFTP/subprocess mocked. Each unit is independently testable by design.

- **Eligibility:** `≥1080p` filter, H.265 detection, preset-by-resolution → correct `eligibility`.
- **Discovery:** upsert (no duplicates on re-scan), watermark advance, scope/filters.
- **Queue:** enqueues eligible items, dedupes already-queued/running, skips excluded.
- **Worker state machine:** smaller→`done`, larger→`skipped_larger`+exclusion, error→`failed`; temp cleanup in all paths.
- **Progress parsing:** the `Encoding NN%` regex maps to `job.progress`.
- **Migration:** CSV → `exclusion` rows; timestamp file → `setting` watermark.
- **Config:** `.env` loading and required-field validation.

---

## 8. New Dependencies

- `SQLAlchemy` — ORM / models / session.
- `pydantic-settings` — typed config from `.env`.
- `pytest` — tests (dev).

(Existing: `requests`, `paramiko`, `tqdm`.)

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Migration data loss | Keep legacy files as `*.migrated`; migration is idempotent and additive. |
| Behavior drift vs. today | Tests assert preserved behavior; CLI `run` mirrors current flow. |
| SQLite locking if Cycle 2 adds a concurrent worker | Single-writer worker + DB-level job-claim guard designed in now. |
| Secrets already leaked | Rotate Sonarr/Radarr keys + SFTP password during this cycle. |

---

## Appendix A — Full roadmap (for context; only Cycle 1 is specced here)

1. **Foundation** *(this spec)* — job/state model, SQLite, secrets, logging, progress capture; headless + CLI.
2. **API + worker** — FastAPI endpoints (browse library, trigger scan/run, job status, SSE live progress, exclusions) + background queue worker thread.
3. **Web UI** — React SPA designed with `frontend-design-pro`, served by FastAPI: library browser, live queue/progress, history, logs. Single-password auth.
4. **Automation** — scheduling, notifications, config editing from UI, run-as-Windows-service.

## Appendix B — Target architecture (reference)

- **Backend:** FastAPI (Python), reuses `transcoder` engine; hosts a background worker thread.
- **State:** SQLite (single file).
- **Live progress:** HandBrake `%` → DB → browser via **SSE**.
- **Frontend:** React SPA built to static files, served by FastAPI (one process, one LAN URL).
- **Deployment:** native Windows background service (not Docker — NVENC/HandBrake on the host GPU).
