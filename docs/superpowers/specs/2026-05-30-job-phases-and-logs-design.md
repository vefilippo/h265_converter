# Job Phases, Live Progress & Per-Job Logs — Design

**Date:** 2026-05-30
**Cycle:** A+B (granular phases + per-job logs). The config-editor area is a
separate later cycle and is out of scope here.

## Goal

Replace the generic `running` job state in the UI with a visible per-phase
label (Downloading / Transcoding / Uploading), make the progress bar move
during all three phases, and let the user read a job's own logs from its detail
dialog.

## Decisions (from brainstorming)

- **Phase as a sub-field, not new states.** `state` keeps its current values
  (`queued/running/done/failed/skipped_larger/cancelled`); a new `phase` column
  carries the granularity. This avoids touching every `state == "running"`
  check (cancel, stale-job recovery, SSE filter, worker controller).
- **Per-job logs stored on the job row** (a `log` text column), so finished
  jobs and post-restart reads still work; no ring-buffer filtering guesswork.
- **Real SFTP byte-progress** for download and upload (not just transcode), so
  the bar moves in all three phases.

## 1. Data Model

Add to `Job` (`models.py`) + one migration:

- `phase: Mapped[str | None]` — `"downloading" | "transcoding" | "uploading"`,
  set only while `state == "running"`, NULL otherwise.
- `log: Mapped[str | None]` (Text) — accumulated per-job log lines.

The existing unused `log_excerpt` Text column is **repurposed**: the migration
adds `phase` and `log`, copies any `log_excerpt` content into `log`, and the
model drops `log_excerpt` in favour of `log`. `progress` (0–100) is unchanged
but now means "percent of the current phase".

Migration approach (SQLite, no native rename): `ALTER TABLE job ADD COLUMN
phase VARCHAR(16)` and `ADD COLUMN log TEXT` guarded by a PRAGMA column check
(idempotent); then `UPDATE job SET log = log_excerpt WHERE log IS NULL AND
log_excerpt IS NOT NULL`. The `log_excerpt` column is left in place physically
(SQLite drop-column is fiddly and it's harmless) but is no longer referenced by
the ORM. This runs from the app lifespan alongside `init_db`/`migrate_legacy`.

## 2. Worker (`engine/worker.py`)

`process_one_job` wraps each step with a phase transition and per-job logging:

1. `phase = "downloading"`, `progress = 0`, commit → `download(...)`.
2. `phase = "transcoding"`, `progress = 0`, commit → HandBrake.
3. `phase = "uploading"`, `progress = 0`, commit → `upload(...)`.
4. On terminal state (`done`/`skipped_larger`/`failed`/`cancelled`),
   `phase = None`.

Helpers:

- `job_log(session, job, msg)` — append `"[HH:MM:SS] {msg}"` to `job.log`
  (newline-joined) **and** `log.info("Job %s: %s", job.id, msg)` so the global
  Logs page keeps working. Commits with the surrounding step.
- A `progress_cb` factory that throttles: only writes/commits `job.progress`
  when the integer percent changes, so SFTP byte callbacks (fired per chunk)
  don't hammer SQLite.

**SFTP failure handling (in-passing fix):** `download_file_via_sftp` /
`upload_file_via_sftp` currently return `{"success": False, "message": ...}` on
error instead of raising, so the worker can't distinguish failure from success.
The worker will check the returned dict and raise `RuntimeError(message)` on
`success is False`, so a failed transfer becomes a `failed` job (caught by the
existing `except Exception` block) rather than a false `done`.

## 3. SFTP client (`sftp_client.py`)

Add an optional `progress_cb: callable | None = None` parameter to both
`upload_file_via_sftp` and `download_file_via_sftp`. Inside the existing
`progress_callback(transferred, total)`, when `progress_cb` is set and
`total > 0`, call `progress_cb(int(transferred / total * 100))`. The tqdm bar
is retained for console use. Signatures stay backwards compatible (new param is
keyword-optional), so existing tests/callers are unaffected.

## 4. API & Schema (`api/`)

- `JobOut` (`schemas.py`) gains `phase: str | None = None`. `log` is **not**
  included in `JobOut` (too heavy for list/stream payloads).
- New endpoint `GET /api/jobs/{job_id}/logs` → `JobLogOut {log: str}` (empty
  string when null). Reuses `_get_job`; 404 when the job is missing.
- `/status` and `/stream` already serialize `JobOut`, so `phase` reaches the
  Dashboard live with no further change.

## 5. Frontend (`web/src/`)

- `types.ts`: `Job` gains `phase: string | null`.
- `queries.ts`: add `useJobLogs(id, enabled)` (polls ~2s while running, static
  when finished — `refetchInterval` gated on an `enabled` flag).
- Badge/label: a `jobStateLabel(job)` helper returns the capitalized `phase`
  when `state === "running" && phase`, else the state. Distinct colors for the
  three phases (extend `jobStateVariant`).
- `Progress` bar: shown for all three running phases (we now have a percent for
  each).
- `Jobs.tsx` detail dialog: add a **Logs** section — a monospace, scrollable
  box rendering `useJobLogs`. Shows "No logs yet" when empty.
- `Dashboard.tsx` "Current Job" card: show the phase label via the same helper.

## 6. Testing

Backend:
- `phase` is set to downloading/transcoding/uploading at each step (fake io
  records `job.phase` when called) and is `None` on terminal states.
- SFTP `progress_cb` maps bytes→percent (call the callback with
  `(transferred, total)` and assert the mapped int).
- A failing SFTP result (`success: False`) makes the job `failed`, not `done`.
- `job.log` accumulates lines across phases; `GET /api/jobs/{id}/logs` returns
  them; 404 for a missing job.
- Existing cancel / stale-recovery / retry tests still pass (state values
  unchanged).

Frontend:
- Badge shows "Transcoding" when `state=running, phase=transcoding`.
- Detail dialog fetches `/api/jobs/{id}/logs` and renders the lines.

## Out of scope

- Config-editor area (API keys, SFTP creds, "new" meaning, etc.) — next cycle.
- Changing the meaning of the `state` enum or the watermark "new" logic.
