# H.265 Converter Service — Cycle 2: API + Background Worker (Design Spec)

**Date:** 2026-05-29
**Status:** Approved (design)
**Scope:** Cycle 2 of 4 — a FastAPI HTTP API plus a continuous background transcode worker, built on the Cycle 1 engine. No web UI yet (Cycle 3).

---

## 1. Context & Goal

Cycle 1 produced a DB-backed engine (`discovery → queue → worker`) driven by a synchronous CLI. Cycle 2 turns that engine into an always-on **service**: an HTTP API to browse the library, trigger scans, manage the job queue, and watch live progress, with a **continuous background worker** that drains the queue one job at a time.

This is the backend the Cycle 3 web UI will consume. It is validated via `curl`/tests in this cycle.

### Fixed constraints (carried from Cycle 1 + decided in brainstorming)
- **Single Windows box, one GPU** → the worker processes **one job at a time**, in-process.
- **Single local user on the LAN** → the server binds to the LAN; **no authentication in Cycle 2** (single password lands in Cycle 3 with the UI).
- **Continuous background worker** → a daemon thread starts with the app and drains the queue automatically as items are enqueued.
- **Full job control** → cancel queued jobs, cancel the running job (kill HandBrake mid-encode), and retry finished jobs.
- **Auto-replace stays automatic** (unchanged from Cycle 1).

### Non-goals for Cycle 2
- No web UI / auth / HTTPS (Cycle 3).
- No scheduling, notifications, run-as-Windows-service (Cycle 4).
- No multi-job parallelism, no distributed/remote workers.

---

## 2. Process & Worker Model

- **App:** a FastAPI application served by **uvicorn**, entry point `python -m transcoder.api` (binds `0.0.0.0` on a configurable port so it's reachable on the LAN).
- **Lifespan startup:** `init_db()` → `migrate_legacy()` (once) → enable SQLite WAL → start the `WorkerController` thread.
- **Lifespan shutdown:** signal the controller to stop, cancel any running job's `cancel_event`, join the thread (bounded timeout).
- The engine modules from Cycle 1 (`discovery`, `queue`, `worker`, `repo`, `models`) are reused. The per-job logic remains `worker.process_one_job`; the controller wraps it in a long-lived loop with cancellation.

---

## 3. Concurrency & Database

- **WAL mode:** a SQLAlchemy connect-time event sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`, allowing API reads concurrently with worker writes.
- **Per-thread sessions:** API requests acquire a session through a FastAPI dependency (`get_session`, one per request, closed in a `finally`). The worker thread owns its **own** session for the lifetime of a job. Sessions are never shared across threads.
- **Progress throttling:** the worker's progress callback commits only when the integer percentage changes (≤101 writes per transcode), bounding WAL growth.
- **No schema change:** `"cancelled"` is simply another `job.state` value. Existing tables are unchanged.

---

## 4. Worker Controller & Cancellation

`transcoder/worker_controller.py` — a single long-lived controller.

### Responsibilities
- **Run loop** (daemon thread): repeatedly select the oldest `queued` job (`order_by id`); if one exists, process it; else wait on a `threading.Event` (`wake`) with a timeout (e.g. 5 s) so newly-enqueued work starts promptly and an idle worker still rechecks periodically.
- **Tracks** `current = (job_id, cancel_event)` while a job runs.
- **`request_cancel(job_id)`**:
  - Job is `queued` → set `state="cancelled"` (worker will skip it).
  - Job is the running job → set its `cancel_event`.
  - Otherwise → no-op (already terminal).
- **`wake()`** — set the wake event (called by enqueue/retry endpoints).
- **`shutdown()`** — set a stop flag, set the current `cancel_event`, wake, and join.

### Cancellation plumbing
- `convert_with_handbrake(..., cancel_event=None)`: inside the stdout/progress loop, if `cancel_event and cancel_event.is_set()`, call `process.kill()` and raise `TranscodeCancelled` (new exception in `transcoder/convert.py`).
- `worker.process_one_job(..., cancel_event=None)`: passes `cancel_event` to `convert`; adds an `except TranscodeCancelled` branch that sets `job.state="cancelled"`, `error_message="cancelled by user"`, `finished_at`. The existing `finally` block removes the partial output + temp file.

### Retry
- `POST /api/jobs/{id}/retry` on a `failed`/`skipped_larger`/`cancelled` job creates a **new** `queued` job for the same `media_item` (only if it has no active job), preserving history, then calls `wake()`. (A retried `skipped_larger` item also needs its exclusion removed and eligibility reset — see §6 Exclusions.)

---

## 5. HTTP API

All endpoints are under `/api`. Responses are JSON via pydantic schemas (`transcoder/api/schemas.py`).

### Library
- `GET /api/library` — paginated list of `media_item`s. Query: `source`, `eligibility`, `limit` (default 100, max 500), `offset`. Returns items + total count.
- `GET /api/library/stats` — counts grouped by `source` and `eligibility` (the Cycle-1 smoke-test breakdown).

### Scan (background)
- `POST /api/scan` — body `{app: all|sonarr|radarr, scope: all|new, show?, movie?}`. Launches discovery in a background task; returns immediately with the current scan status. Discovery is slow (thousands of episode-file calls), so it must not block the request.
- `GET /api/scan/status` — in-memory status of the most recent scan: `idle|running|done|error`, started/finished timestamps, per-source counts, error message if any. (Single user → a single in-memory status object is sufficient; not persisted.)

### Queue / jobs
- `POST /api/enqueue` — body `{source?: sonarr|radarr}`. Calls `enqueue_eligible`, returns count created, calls `wake()`.
- `GET /api/jobs` — paginated; query `state`, `limit`, `offset`. Each item includes the joined media-item title (use `joinedload` to avoid N+1).
- `GET /api/jobs/{id}` — full job detail.
- `POST /api/jobs/{id}/cancel` — `controller.request_cancel(id)`. Returns the updated job state.
- `POST /api/jobs/{id}/retry` — re-enqueue as described in §4.

### Exclusions
- `GET /api/exclusions` — list.
- `POST /api/exclusions` — body `{source, key, reason}` (manual exclusion).
- `DELETE /api/exclusions/{id}` — remove the row. Eligibility is recomputed on the next scan; the response notes that a re-scan is required for the item to become eligible again.

### Status & live progress
- `GET /api/status` — `{worker_alive, current_job: {id, progress, title}|null, queue_length, stats}`.
- `GET /api/stream` — **Server-Sent Events**. The async generator polls the DB roughly once per second and emits events when the current job's progress or any job's state changes: `event: progress` / `event: job` with JSON payloads, plus periodic `event: heartbeat`. DB-polling is used deliberately to avoid cross-thread async bridging; it is adequate for one local consumer.

---

## 6. Behavior Notes

- **Exclusions vs. eligibility:** removing an exclusion does not by itself flip a `media_item` back to `needs_transcode`; the next scan recomputes eligibility. `retry` on a `skipped_larger` job therefore also deletes the matching `output_larger` exclusion and sets that item's `eligibility="needs_transcode"` so the new job will run.
- **Idempotent enqueue** (Cycle 1) still applies — items with an active (`queued`/`running`) job are not re-queued.
- **Scan concurrency:** only one scan runs at a time; a `POST /api/scan` while a scan is `running` returns `409 Conflict`.

---

## 7. Project Structure

```
source_code/transcoder/
  api/
    __init__.py
    app.py            # create_app(): FastAPI + lifespan (startup/shutdown), mounts routers
    deps.py           # get_session() request-scoped dependency
    schemas.py        # pydantic request/response models
    state.py          # module-level singletons: WorkerController instance, ScanStatus
    routers/
      __init__.py
      library.py
      scan.py
      jobs.py
      exclusions.py
      stream.py       # /status + /stream (SSE)
    __main__.py       # uvicorn.run(create_app(), host, port) — `python -m transcoder.api`
  worker_controller.py  # background thread, wake event, cancellation registry
  convert.py            # + cancel_event param, TranscodeCancelled exception
  engine/worker.py      # + cancel_event param, "cancelled" terminal state
  db.py                 # + WAL/busy_timeout connect event
```

New dependencies: `fastapi`, `uvicorn[standard]`, `httpx` (TestClient/test dep). Existing: SQLAlchemy, pydantic-settings, pytest, requests, paramiko, tqdm.

---

## 8. Error Handling

- API validation via pydantic; unknown ids → `404`; conflicting scan → `409`.
- Engine/DB exceptions in request handlers → `500` with a logged, sanitized message (no secrets/paths leaked beyond what logs already contain).
- Worker exceptions per job are already isolated (Cycle 1): a failing job is marked `failed` and the loop continues; the controller thread never dies on a single job.
- SSE generator guards against client disconnects (stop on `asyncio.CancelledError`).

---

## 9. Testing

`pytest` + FastAPI `TestClient`, in-memory SQLite, `get_session` overridden.

- **WorkerController** (inject a fake `process_one_job`): drains queued jobs; `wake` unblocks the loop; queued-cancel sets `state="cancelled"` and skips; running-cancel sets the job's `cancel_event`; `shutdown` joins cleanly.
- **convert cancellation** (inject a fake `process` whose stdout yields progress lines): when `cancel_event` is set, `process.kill()` is called and `TranscodeCancelled` is raised.
- **worker** "cancelled" path: `process_one_job` with a fake convert that raises `TranscodeCancelled` → job `cancelled`, temp/output cleaned.
- **API**: library list + filters + pagination, stats, enqueue (count + dedupe), jobs list/detail, cancel-queued, retry (new job created; skipped_larger exclusion cleared), exclusions CRUD, status payload, `409` on concurrent scan, `404`s.
- **SSE smoke**: `GET /api/stream` yields at least one well-formed event then disconnects.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| SQLite write contention (worker + API) | WAL + busy_timeout; short transactions; throttled progress writes |
| Killing HandBrake leaves a partial file | Worker `finally` already removes output + temp; cancel path exercised by tests |
| SSE polling overhead | 1 Hz poll, single local consumer; emit only on change + heartbeat |
| Long scans blocking the API | Scans run as background tasks; `409` prevents overlap |
| Cross-thread session misuse | Per-request + per-worker sessions; never shared; documented in deps |

---

## Appendix — Roadmap position

1. **Foundation** — *done, merged (Cycle 1).*
2. **API + worker** *(this spec)* — FastAPI + continuous background worker, full job control, SSE, no auth.
3. **Web UI** — React SPA (frontend-design-pro), served by FastAPI; single-password auth; consumes this API + SSE.
4. **Automation** — scheduling, notifications, config editing from the UI, run-as-Windows-service.
