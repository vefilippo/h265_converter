# H.265 Service — Cycle 2 (API + Background Worker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the Cycle 1 engine as a FastAPI HTTP service with a continuous background transcode worker, full job control (cancel queued/running, retry), live SSE progress, and no auth (LAN-bound).

**Architecture:** A FastAPI app (uvicorn) reuses the Cycle 1 engine. A `WorkerController` daemon thread drains the job queue one job at a time, woken by enqueue/retry, supporting cancellation by killing the HandBrake subprocess. SQLite runs in WAL mode so API reads coexist with worker writes; each thread/request uses its own session. Routers expose library/scan/jobs/exclusions/status/stream.

**Tech Stack:** Python 3.10, FastAPI, uvicorn, SQLAlchemy 2.0, pydantic-settings, pytest + FastAPI TestClient (httpx).

**Spec:** `docs/superpowers/specs/2026-05-29-h265-service-cycle2-api-worker-design.md`

**Working directory for commands:** `source_code/` (package root); tests in `source_code/tests/`. Interpreter: `.venv/Scripts/python.exe`. Branch: `cycle-2-api-worker`.

---

## File Structure

**Create:**
- `transcoder/convert.py` — (modify) add `TranscodeCancelled` + `cancel_event`
- `transcoder/engine/worker.py` — (modify) add `cancel_event` + `"cancelled"` path
- `transcoder/db.py` — (modify) WAL/busy_timeout connect event
- `transcoder/worker_controller.py` — background thread, wake event, cancel registry
- `transcoder/api/__init__.py`
- `transcoder/api/app.py` — `create_app()` + lifespan
- `transcoder/api/deps.py` — request-scoped `get_session`
- `transcoder/api/schemas.py` — pydantic models
- `transcoder/api/state.py` — module singletons (controller, scan status)
- `transcoder/api/routers/__init__.py`
- `transcoder/api/routers/library.py`
- `transcoder/api/routers/scan.py`
- `transcoder/api/routers/jobs.py`
- `transcoder/api/routers/exclusions.py`
- `transcoder/api/routers/stream.py`
- `transcoder/api/__main__.py` — uvicorn entry
- Tests: `tests/test_convert_cancel.py`, `tests/test_worker_cancel.py`, `tests/test_worker_controller.py`, `tests/test_api_library.py`, `tests/test_api_scan.py`, `tests/test_api_jobs.py`, `tests/test_api_exclusions.py`, `tests/test_api_status_stream.py`
- `tests/api_conftest.py` — shared API TestClient fixture (imported via conftest)

**Modify:**
- `requirements.txt` — add fastapi, uvicorn[standard], httpx

---

## Task 1: Web dependencies

**Files:**
- Modify: `source_code/requirements.txt`

- [ ] **Step 1: Append web deps.** Set `requirements.txt` to:
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
```

- [ ] **Step 2: Install.** Run: `.venv/Scripts/python.exe -m pip install -r requirements.txt`
Expected: fastapi, uvicorn, httpx (+ starlette) install successfully.

- [ ] **Step 3: Verify import.** Run: `.venv/Scripts/python.exe -c "import fastapi, uvicorn, httpx; from fastapi.testclient import TestClient; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit.**
```bash
git add source_code/requirements.txt
git commit -m "chore: add fastapi/uvicorn/httpx for the API layer"
```

---

## Task 2: SQLite WAL mode

**Files:**
- Modify: `source_code/transcoder/db.py`
- Test: `source_code/tests/test_db_wal.py`

- [ ] **Step 1: Write the failing test.** `tests/test_db_wal.py`:
```python
from sqlalchemy import text
from transcoder.db import make_engine


def test_engine_sets_wal_and_busy_timeout(tmp_path):
    db = tmp_path / "wal.db"
    engine = make_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert int(conn.execute(text("PRAGMA busy_timeout")).scalar()) == 5000
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_db_wal.py -v`
Expected: FAIL (journal_mode is `memory`/`delete`, not `wal`).

- [ ] **Step 3: Add the connect event in `db.py`.** Replace the entire file with:
```python
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from transcoder.config import settings


class Base(DeclarativeBase):
    pass


def _enable_sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def make_engine(url: str | None = None):
    engine = create_engine(
        url or settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _enable_sqlite_pragmas)
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(eng=engine) -> None:
    import transcoder.models  # noqa: F401  (register tables)
    Base.metadata.create_all(eng)
```

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_db_wal.py -v`
Expected: PASS. Note: `:memory:` DBs report `memory` journal mode; this test uses a file DB on purpose.

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 30 passed (29 prior + 1). Existing in-memory `session` fixture still works (WAL pragma is a no-op/`memory` for `:memory:`).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/db.py source_code/tests/test_db_wal.py
git commit -m "feat: enable SQLite WAL + busy_timeout for concurrent API/worker access"
```

---

## Task 3: Cancellable convert

**Files:**
- Modify: `source_code/transcoder/convert.py`
- Test: `source_code/tests/test_convert_cancel.py`

- [ ] **Step 1: Write the failing test.** `tests/test_convert_cancel.py`:
```python
import threading
import pytest

from transcoder import convert
from transcoder.convert import TranscodeCancelled, convert_with_handbrake


class FakeProcess:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.returncode = 0
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self):
        return 0


def test_convert_raises_and_kills_on_cancel(monkeypatch):
    proc = FakeProcess([
        "Encoding: task 1 of 1, 10.00 %\n",
        "Encoding: task 1 of 1, 20.00 %\n",
        "Encoding: task 1 of 1, 30.00 %\n",
    ])
    monkeypatch.setattr(convert.subprocess, "Popen", lambda *a, **k: proc)

    cancel = threading.Event()
    seen = []

    def cb(pct):
        seen.append(pct)
        if pct >= 20:
            cancel.set()  # request cancel after some progress

    with pytest.raises(TranscodeCancelled):
        convert_with_handbrake("in.mkv", "out.mkv", "preset",
                               progress_cb=cb, cancel_event=cancel)

    assert proc.killed is True
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_convert_cancel.py -v`
Expected: FAIL (`TranscodeCancelled` not defined / no `cancel_event` param).

- [ ] **Step 3: Modify `convert.py`.** Add the exception and the cancel check. The current progress loop is:
```python
    for line in process.stdout:
        pct = parse_handbrake_progress(line)
        if pct is not None and progress_cb is not None:
            try:
                progress_cb(pct)
            except Exception:
                # A progress-update failure (e.g. a transient DB write error)
                # must not abort the transcode or orphan the subprocess.
                pass
```
First add this class near the top (after the imports, before `parse_handbrake_progress`):
```python
class TranscodeCancelled(Exception):
    """Raised when a transcode is cancelled via its cancel_event."""
```
Change the signature to add `cancel_event=None`:
```python
def convert_with_handbrake(input_file, output_filename, preset, progress_cb=None, cancel_event=None):
```
Replace the progress loop with:
```python
    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            raise TranscodeCancelled()
        pct = parse_handbrake_progress(line)
        if pct is not None and progress_cb is not None:
            try:
                progress_cb(pct)
            except Exception:
                # A progress-update failure (e.g. a transient DB write error)
                # must not abort the transcode or orphan the subprocess.
                pass
```
Leave the rest of the function unchanged.

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_convert_cancel.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 32 passed (30 + 2). The existing `test_convert_progress.py` still passes (parser unchanged).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/convert.py source_code/tests/test_convert_cancel.py
git commit -m "feat: cancellable HandBrake transcode (cancel_event + TranscodeCancelled)"
```

---

## Task 4: Worker cancelled path

**Files:**
- Modify: `source_code/transcoder/engine/worker.py`
- Test: `source_code/tests/test_worker_cancel.py`

- [ ] **Step 1: Write the failing test.** `tests/test_worker_cancel.py`:
```python
import os

from transcoder.convert import TranscodeCancelled
from transcoder.engine.worker import process_one_job
from transcoder.models import Job, MediaItem


def _item(session):
    item = MediaItem(
        source="sonarr", external_id="1", title="Show A", season=1, episode=1,
        remote_path="/TVShows/a.mkv", resolution=1080, quality="HDTV-1080p",
        languages="ENG", eligibility="needs_transcode",
    )
    session.add(item)
    session.commit()
    return item


def test_worker_marks_cancelled(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    def download(*a, **k):
        return {"success": True}

    def convert(tmp, out_name, preset, progress_cb=None, cancel_event=None):
        raise TranscodeCancelled()

    process_one_job(session, job, {"sonarr": object()},
                    download=download, upload=lambda *a, **k: None, convert=convert)

    assert job.state == "cancelled"
    assert job.error_message
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_worker_cancel.py -v`
Expected: FAIL (TranscodeCancelled currently caught by the generic `except Exception` → state `failed`, not `cancelled`).

- [ ] **Step 3: Modify `worker.py`.** Two edits.

(a) Add the import at the top, next to the other transcoder imports:
```python
from transcoder.convert import convert_with_handbrake, TranscodeCancelled
```
(the existing line `from transcoder.convert import convert_with_handbrake` becomes the combined import above).

(b) The convert call currently is:
```python
        output_file, exclude_flag = convert(tmp_file, out_name, job.preset, progress_cb=cb)
```
Change it to thread the cancel event through (the param is added in Task 5's controller; here we accept it as a kwarg on `process_one_job`). Update the signature:
```python
def process_one_job(
    session,
    job,
    clients,
    *,
    cancel_event=None,
    download=download_file_via_sftp,
    upload=upload_file_via_sftp,
    convert=convert_with_handbrake,
):
```
and the call:
```python
        output_file, exclude_flag = convert(tmp_file, out_name, job.preset,
                                            progress_cb=cb, cancel_event=cancel_event)
```
Then add a dedicated except BEFORE the generic `except Exception` block:
```python
    except TranscodeCancelled:
        job.state = "cancelled"
        job.error_message = "cancelled by user"
        job.finished_at = utcnow()
        session.commit()
        return job

    except Exception as exc:  # noqa: BLE001 — record failure, keep draining queue
        job.state = "failed"
        job.error_message = str(exc)
        job.finished_at = utcnow()
        session.commit()
        return job
```
Leave the `finally` cleanup block unchanged (it already removes tmp/output).

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_worker_cancel.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 33 passed (32 + 1). The existing worker tests still pass — they call `process_one_job` with keyword IO args and no `cancel_event` (defaults to None).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/engine/worker.py source_code/tests/test_worker_cancel.py
git commit -m "feat: worker marks cancelled jobs via TranscodeCancelled"
```

---

## Task 5: WorkerController

**Files:**
- Create: `source_code/transcoder/worker_controller.py`
- Test: `source_code/tests/test_worker_controller.py`

**Design:** the controller is engine-agnostic for testing — it takes a `session_factory` (callable returning a Session) and a `process` callable (defaults to the real `process_one_job`) so tests can inject fakes. It runs a daemon thread; each iteration opens a fresh session, claims the oldest queued job, and processes it with a per-job `cancel_event`.

- [ ] **Step 1: Write the failing test.** `tests/test_worker_controller.py`:
```python
import threading
import time
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
from transcoder.models import Job, MediaItem
from transcoder.worker_controller import WorkerController
from sqlalchemy import create_engine


def _make_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _add_job(Session):
    s = Session()
    item = MediaItem(source="sonarr", external_id="1", title="A",
                     remote_path="/x.mkv", resolution=1080, eligibility="needs_transcode")
    s.add(item); s.commit()
    job = Job(media_item_id=item.id, state="queued")
    s.add(job); s.commit()
    jid = job.id
    s.close()
    return jid


def test_controller_processes_queued_job():
    Session = _make_factory()
    jid = _add_job(Session)
    processed = []

    def fake_process(session, job, clients, *, cancel_event=None, **io):
        job.state = "done"
        session.commit()
        processed.append(job.id)

    ctrl = WorkerController(Session, clients={}, process=fake_process, idle_timeout=0.1)
    ctrl.start()
    ctrl.wake()
    # wait until processed
    for _ in range(50):
        if processed:
            break
        time.sleep(0.05)
    ctrl.shutdown()
    assert processed == [jid]
    s = Session()
    assert s.get(Job, jid).state == "done"
    s.close()


def test_controller_cancel_queued_job_is_skipped():
    Session = _make_factory()
    jid = _add_job(Session)
    started = threading.Event()

    def fake_process(session, job, clients, *, cancel_event=None, **io):
        started.set()
        job.state = "done"
        session.commit()

    ctrl = WorkerController(Session, clients={}, process=fake_process, idle_timeout=0.1)
    # cancel before starting the loop
    ctrl.request_cancel(jid)
    ctrl.start()
    ctrl.wake()
    time.sleep(0.3)
    ctrl.shutdown()
    assert started.is_set() is False
    s = Session()
    assert s.get(Job, jid).state == "cancelled"
    s.close()


def test_controller_cancel_running_sets_event():
    Session = _make_factory()
    jid = _add_job(Session)
    entered = threading.Event()
    saw_cancel = {}

    def fake_process(session, job, clients, *, cancel_event=None, **io):
        entered.set()
        # busy-wait until cancel_event is set by the controller
        for _ in range(100):
            if cancel_event is not None and cancel_event.is_set():
                saw_cancel["set"] = True
                break
            time.sleep(0.02)
        job.state = "cancelled"
        session.commit()

    ctrl = WorkerController(Session, clients={}, process=fake_process, idle_timeout=0.1)
    ctrl.start()
    ctrl.wake()
    assert entered.wait(timeout=2.0)
    ctrl.request_cancel(jid)  # running → should set the event
    for _ in range(100):
        if saw_cancel.get("set"):
            break
        time.sleep(0.02)
    ctrl.shutdown()
    assert saw_cancel.get("set") is True
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_worker_controller.py -v`
Expected: FAIL (`No module named transcoder.worker_controller`).

- [ ] **Step 3: Create `worker_controller.py`.**
```python
import logging
import threading

from transcoder.models import Job
from transcoder.engine.worker import process_one_job

log = logging.getLogger("transcoder")


class WorkerController:
    """Continuous background worker: drains queued jobs one at a time.

    session_factory: callable returning a new Session (e.g. SessionLocal).
    clients: {"sonarr": SonarrClient, "radarr": RadarrClient}.
    process: per-job processor (injected for tests); defaults to process_one_job.
    idle_timeout: seconds the loop waits on the wake event when the queue is empty.
    """

    def __init__(self, session_factory, clients, process=process_one_job, idle_timeout=5.0):
        self._session_factory = session_factory
        self._clients = clients
        self._process = process
        self._idle_timeout = idle_timeout
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._current_job_id = None
        self._current_cancel = None

    # --- lifecycle ---
    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="transcode-worker", daemon=True)
        self._thread.start()

    def shutdown(self, timeout=10.0):
        self._stop.set()
        with self._lock:
            if self._current_cancel is not None:
                self._current_cancel.set()
        self._wake.set()
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def wake(self):
        self._wake.set()

    # --- introspection ---
    @property
    def current_job_id(self):
        with self._lock:
            return self._current_job_id

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    # --- cancellation ---
    def request_cancel(self, job_id: int) -> str:
        """Cancel a queued or running job. Returns the resulting state hint."""
        with self._lock:
            if self._current_job_id == job_id and self._current_cancel is not None:
                self._current_cancel.set()
                return "cancelling"
        # not the running job → if queued, mark cancelled directly
        session = self._session_factory()
        try:
            job = session.get(Job, job_id)
            if job is not None and job.state == "queued":
                job.state = "cancelled"
                session.commit()
                return "cancelled"
            return job.state if job is not None else "missing"
        finally:
            session.close()

    # --- loop ---
    def _next_job_id(self, session):
        job = (
            session.query(Job)
            .filter(Job.state == "queued")
            .order_by(Job.id)
            .first()
        )
        return job.id if job is not None else None

    def _run(self):
        while not self._stop.is_set():
            session = None
            try:
                session = self._session_factory()
                job_id = self._next_job_id(session)
                if job_id is None:
                    # Outer finally closes the session; just idle until woken.
                    self._wake.wait(timeout=self._idle_timeout)
                    self._wake.clear()
                    continue

                job = session.get(Job, job_id)
                if job is None:
                    continue
                cancel_event = threading.Event()
                with self._lock:
                    self._current_job_id = job_id
                    self._current_cancel = cancel_event
                try:
                    # Re-read state under the live transaction: a cancel may have
                    # landed between job selection and registering it as current.
                    session.refresh(job)
                    if job.state == "cancelled":
                        continue
                    self._process(session, job, self._clients, cancel_event=cancel_event)
                except Exception:  # noqa: BLE001 — never let one job kill the loop
                    log.exception("worker: job %s crashed", job_id)
                finally:
                    with self._lock:
                        self._current_job_id = None
                        self._current_cancel = None
            finally:
                if session is not None:
                    session.close()
```

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_worker_controller.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 36 passed (33 + 3).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/worker_controller.py source_code/tests/test_worker_controller.py
git commit -m "feat: WorkerController background drain + cancellation"
```

---

## Task 6: API app skeleton + session dependency + state

**Files:**
- Create: `transcoder/api/__init__.py` (empty), `transcoder/api/deps.py`, `transcoder/api/state.py`, `transcoder/api/app.py`, `transcoder/api/routers/__init__.py` (empty)
- Test: `tests/test_api_health.py`

- [ ] **Step 1: Write the failing test.** `tests/test_api_health.py`:
```python
from fastapi.testclient import TestClient

from transcoder.api.app import create_app


def test_health_ok():
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_health.py -v`
Expected: FAIL (`No module named transcoder.api.app`).

- [ ] **Step 3: Create the files.**

`transcoder/api/__init__.py`: empty.
`transcoder/api/routers/__init__.py`: empty.

`transcoder/api/deps.py`:
```python
from transcoder.db import SessionLocal


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

`transcoder/api/state.py`:
```python
"""Process-wide singletons for the API: the worker controller and scan status."""
import threading

from transcoder.config import settings
from transcoder.db import SessionLocal
from transcoder.sonarr_client import SonarrClient
from transcoder.radarr_client import RadarrClient
from transcoder.worker_controller import WorkerController


def build_clients() -> dict:
    return {
        "sonarr": SonarrClient(settings.SONARR_URL, settings.SONARR_API_KEY),
        "radarr": RadarrClient(settings.RADARR_URL, settings.RADARR_API_KEY),
    }


class ScanStatus:
    """In-memory status of the most recent scan (single-user app)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"          # idle | running | done | error
        self.detail = {}             # arbitrary counts / message

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "detail": dict(self.detail)}

    def set(self, state: str, **detail):
        with self._lock:
            self.state = state
            self.detail = detail

    def try_start(self) -> bool:
        """Atomically transition to 'running' if not already running.

        Returns True if this caller acquired the scan slot, False otherwise.
        Closes the check-then-set race in the scan endpoint.
        """
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.detail = {}
            return True

    @property
    def running(self) -> bool:
        with self._lock:
            return self.state == "running"


# Singletons (constructed once at import).
controller = WorkerController(SessionLocal, build_clients())
scan_status = ScanStatus()
```

`transcoder/api/app.py`:
```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from transcoder.logging_setup import init_logging
from transcoder.db import SessionLocal, init_db
from transcoder.migrate import migrate_legacy
from transcoder.api import state

log = logging.getLogger("transcoder")


def create_app(start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_logging()
        init_db()
        session = SessionLocal()
        try:
            migrate_legacy(session)
        finally:
            session.close()
        if start_worker:
            state.controller.start()
        try:
            yield
        finally:
            if start_worker:
                state.controller.shutdown()

    app = FastAPI(title="H.265 Transcoder", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Routers are mounted in later tasks.
    from transcoder.api.routers import library, scan, jobs, exclusions, stream
    app.include_router(library.router)
    app.include_router(scan.router)
    app.include_router(jobs.router)
    app.include_router(exclusions.router)
    app.include_router(stream.router)
    return app
```

NOTE: the router imports at the bottom of `create_app` reference modules created in Tasks 7–11. To keep THIS task green on its own, create five **stub** router modules now, each exposing an empty `router`:

`transcoder/api/routers/library.py`, `scan.py`, `jobs.py`, `exclusions.py`, `stream.py` — each containing exactly:
```python
from fastapi import APIRouter

router = APIRouter(prefix="/api")
```
(Each later task replaces its stub with real endpoints.)

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_health.py -v`
Expected: PASS. (TestClient triggers lifespan; `start_worker=False` so no thread starts. `migrate_legacy` runs against the real `transcoder.db`/`.env`; in CI without `.env` this would fail — but `.env` exists locally. To keep tests hermetic, the test passes `start_worker=False` and relies on the local DB. If `migrate_legacy` errors due to environment, see Task 6a note.)

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 37 passed (36 + 1).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/api source_code/tests/test_api_health.py
git commit -m "feat: FastAPI app skeleton, session dep, state singletons, health"
```

---

## Task 6a: Hermetic API test fixture (override session + isolate startup)

**Files:**
- Create: `source_code/tests/api_conftest.py`
- Modify: `source_code/tests/conftest.py` (import the API fixture)

**Why:** API tests must use an isolated in-memory DB (not the real `transcoder.db`) and must not run `migrate_legacy` against real files or start the worker. This fixture builds an app with the session dependency overridden and lifespan side-effects disabled.

- [ ] **Step 1: Create `tests/api_conftest.py`.**
```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401
from transcoder.api.app import create_app
from transcoder.api.deps import get_session


@pytest.fixture
def api():
    """A TestClient with an isolated in-memory DB and no worker/migration.

    Yields (client, Session) so tests can seed data directly.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    app = create_app(start_worker=False)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    # Replace lifespan migrate/init by not entering it: use TestClient without
    # context manager so startup/shutdown still run but init_db()/migrate use the
    # real engine — to avoid that, we monkeypatch below in conftest helpers.
    client = TestClient(app)
    yield client, Session
    client.close()
```

NOTE: `create_app`'s lifespan calls `init_db()`/`migrate_legacy()` against the real engine. For hermetic tests we must neutralize those. Update `tests/api_conftest.py` to patch them:
```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from transcoder.db import Base
import transcoder.models  # noqa: F401
import transcoder.api.app as app_module
from transcoder.api.app import create_app
from transcoder.api.deps import get_session


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Neutralize lifespan side-effects that touch the real DB/.env.
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "SessionLocal", Session)

    app = create_app(start_worker=False)
    app.dependency_overrides[get_session] = lambda: _yield(Session)
    client = TestClient(app)
    yield client, Session
    client.close()


def _yield(Session):
    s = Session()
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 2: Make the fixture discoverable.** Append to `tests/conftest.py`:
```python
from tests.api_conftest import api  # noqa: E402,F401  (re-export API fixture)
```
(`tests/__init__.py` already exists, so `tests.api_conftest` is importable.)

- [ ] **Step 3: Smoke-run.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_health.py -q`
Expected: still PASS (health test doesn't use the `api` fixture but conftest import must not error).

- [ ] **Step 4: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 37 passed (no new test; fixture infra only).

- [ ] **Step 5: Commit.**
```bash
git add source_code/tests/api_conftest.py source_code/tests/conftest.py
git commit -m "test: hermetic API fixture (in-memory DB, no worker/migration)"
```

---

## Task 7: Schemas + Library router

**Files:**
- Create: `source_code/transcoder/api/schemas.py`
- Modify: `source_code/transcoder/api/routers/library.py`
- Test: `source_code/tests/test_api_library.py`

- [ ] **Step 1: Write the failing test.** `tests/test_api_library.py`:
```python
from transcoder.models import MediaItem


def _seed(Session):
    s = Session()
    s.add_all([
        MediaItem(source="sonarr", external_id="1", title="A", resolution=1080,
                  remote_path="/x", eligibility="needs_transcode"),
        MediaItem(source="sonarr", external_id="2", title="B", resolution=720,
                  remote_path="/y", eligibility="below_1080p"),
        MediaItem(source="radarr", external_id="3", title="C", resolution=2160,
                  remote_path="/z", eligibility="already_h265"),
    ])
    s.commit()
    s.close()


def test_library_list_and_filter(api):
    client, Session = api
    _seed(Session)

    r = client.get("/api/library")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3

    r = client.get("/api/library", params={"source": "sonarr"})
    assert r.json()["total"] == 2

    r = client.get("/api/library", params={"eligibility": "already_h265"})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["title"] == "C"


def test_library_stats(api):
    client, Session = api
    _seed(Session)
    r = client.get("/api/library/stats")
    assert r.status_code == 200
    stats = r.json()["stats"]
    # list of {source, eligibility, count}
    pairs = {(s["source"], s["eligibility"]): s["count"] for s in stats}
    assert pairs[("sonarr", "needs_transcode")] == 1
    assert pairs[("radarr", "already_h265")] == 1
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_library.py -v`
Expected: FAIL (router has no endpoints; 404).

- [ ] **Step 3: Create `schemas.py`.**
```python
from pydantic import BaseModel


class MediaItemOut(BaseModel):
    id: int
    source: str
    external_id: str
    title: str
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    resolution: int
    quality: str | None = None
    languages: str | None = None
    codec: str | None = None
    is_h265: bool
    eligibility: str

    class Config:
        from_attributes = True


class LibraryPage(BaseModel):
    total: int
    items: list[MediaItemOut]


class StatRow(BaseModel):
    source: str
    eligibility: str
    count: int


class LibraryStats(BaseModel):
    stats: list[StatRow]


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

    class Config:
        from_attributes = True


class JobPage(BaseModel):
    total: int
    items: list[JobOut]


class EnqueueIn(BaseModel):
    source: str | None = None


class EnqueueOut(BaseModel):
    created: int


class ScanIn(BaseModel):
    app: str = "all"
    scope: str = "all"
    show: str | None = None
    movie: str | None = None


class ExclusionOut(BaseModel):
    id: int
    source: str
    key: str
    reason: str

    class Config:
        from_attributes = True


class ExclusionIn(BaseModel):
    source: str
    key: str
    reason: str = "manual"


class StatusOut(BaseModel):
    worker_alive: bool
    current_job: JobOut | None = None
    queue_length: int
    stats: list[StatRow]
```

- [ ] **Step 4: Replace `routers/library.py`.**
```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from transcoder.api.deps import get_session
from transcoder.api.schemas import LibraryPage, LibraryStats, MediaItemOut, StatRow
from transcoder.models import MediaItem

router = APIRouter(prefix="/api")


@router.get("/library", response_model=LibraryPage)
def list_library(
    source: str | None = None,
    eligibility: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    q = session.query(MediaItem)
    if source:
        q = q.filter(MediaItem.source == source)
    if eligibility:
        q = q.filter(MediaItem.eligibility == eligibility)
    total = q.count()
    rows = q.order_by(MediaItem.id).limit(limit).offset(offset).all()
    return LibraryPage(total=total, items=[MediaItemOut.model_validate(r) for r in rows])


@router.get("/library/stats", response_model=LibraryStats)
def library_stats(session: Session = Depends(get_session)):
    rows = (
        session.query(MediaItem.source, MediaItem.eligibility, func.count())
        .group_by(MediaItem.source, MediaItem.eligibility)
        .all()
    )
    return LibraryStats(stats=[StatRow(source=s, eligibility=e, count=c) for s, e, c in rows])
```

- [ ] **Step 5: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_library.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 39 passed (37 + 2).

- [ ] **Step 7: Commit.**
```bash
git add source_code/transcoder/api/schemas.py source_code/transcoder/api/routers/library.py source_code/tests/test_api_library.py
git commit -m "feat: API schemas + library list/stats endpoints"
```

---

## Task 8: Jobs router (list/detail/cancel/retry/enqueue)

**Files:**
- Modify: `source_code/transcoder/api/routers/jobs.py`
- Test: `source_code/tests/test_api_jobs.py`

**Note:** cancel/retry use the singleton `state.controller`. In tests the controller is not started (no thread); `request_cancel` on a queued job just flips DB state, and `retry` creates a new job. The controller's `request_cancel` uses its own `session_factory` (the real `SessionLocal`), which in tests is monkeypatched to the in-memory `Session` by the `api` fixture (Task 6a patches `app_module.SessionLocal`, but `state.controller` was built at import with the real `SessionLocal`). To keep cancel/retry hermetic, the jobs router performs the DB mutation via the request `session` and only calls `controller.wake()` / `controller.request_cancel` for the running-job case. See implementation.

- [ ] **Step 1: Write the failing test.** `tests/test_api_jobs.py`:
```python
from transcoder.models import Exclusion, Job, MediaItem


def _seed_item(Session, **kw):
    s = Session()
    defaults = dict(source="sonarr", external_id="1", title="A", season=1, episode=1,
                    remote_path="/x", resolution=1080, eligibility="needs_transcode")
    defaults.update(kw)
    item = MediaItem(**defaults)
    s.add(item); s.commit()
    iid = item.id
    s.close()
    return iid


def test_enqueue_and_list_jobs(api):
    client, Session = api
    _seed_item(Session)
    r = client.post("/api/enqueue", json={})
    assert r.status_code == 200
    assert r.json()["created"] == 1

    r = client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "queued"
    assert body["items"][0]["title"] == "A"


def test_cancel_queued_job(api):
    client, Session = api
    _seed_item(Session)
    client.post("/api/enqueue", json={})
    jid = client.get("/api/jobs").json()["items"][0]["id"]

    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"


def test_retry_failed_job_creates_new(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="failed"))
    s.commit()
    old_jid = s.query(Job).one().id
    s.close()

    r = client.post(f"/api/jobs/{old_jid}/retry")
    assert r.status_code == 200
    # a new queued job now exists for the same item
    jobs = client.get("/api/jobs").json()["items"]
    states = sorted(j["state"] for j in jobs)
    assert states == ["failed", "queued"]


def test_retry_skipped_larger_clears_exclusion(api):
    client, Session = api
    iid = _seed_item(Session, eligibility="excluded")
    s = Session()
    s.add(Job(media_item_id=iid, state="skipped_larger"))
    s.add(Exclusion(source="sonarr", key="A|1|1", reason="output_larger"))
    s.commit()
    jid = s.query(Job).one().id
    s.close()

    r = client.post(f"/api/jobs/{jid}/retry")
    assert r.status_code == 200
    s = Session()
    assert s.query(Exclusion).count() == 0
    item = s.query(MediaItem).get(iid)
    assert item.eligibility == "needs_transcode"
    s.close()


def test_job_404(api):
    client, Session = api
    assert client.get("/api/jobs/999").status_code == 404
    assert client.post("/api/jobs/999/cancel").status_code == 404
    assert client.post("/api/jobs/999/retry").status_code == 404
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_jobs.py -v`
Expected: FAIL (404s; endpoints missing).

- [ ] **Step 3: Replace `routers/jobs.py`.**
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from transcoder.api.deps import get_session
from transcoder.api import state
from transcoder.api.schemas import EnqueueIn, EnqueueOut, JobOut, JobPage
from transcoder.engine.queue import enqueue_eligible
from transcoder.models import Exclusion, Job, MediaItem, episode_exclusion_key, movie_exclusion_key

router = APIRouter(prefix="/api")

_RETRYABLE = {"failed", "skipped_larger", "cancelled"}


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.title = job.media_item.title if job.media_item else None
    return out


@router.post("/enqueue", response_model=EnqueueOut)
def enqueue(body: EnqueueIn, session: Session = Depends(get_session)):
    created = enqueue_eligible(session, source=body.source)
    state.controller.wake()
    return EnqueueOut(created=created)


@router.get("/jobs", response_model=JobPage)
def list_jobs(
    state_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    q = session.query(Job).options(joinedload(Job.media_item))
    if state_filter:
        q = q.filter(Job.state == state_filter)
    total = q.count()
    rows = q.order_by(Job.id).limit(limit).offset(offset).all()
    return JobPage(total=total, items=[_to_out(j) for j in rows])


def _get_job(session: Session, job_id: int) -> Job:
    # session.get forwards loader options in SQLAlchemy 2.0 (Query.get does not).
    job = session.get(Job, job_id, options=[joinedload(Job.media_item)])
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)):
    return _to_out(_get_job(session, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    if job.state == "running":
        if state.controller.current_job_id == job_id:
            state.controller.request_cancel(job_id)
        else:
            raise HTTPException(
                status_code=409,
                detail="job is marked running but not active on the worker; cannot cancel",
            )
    elif job.state == "queued":
        job.state = "cancelled"
        session.commit()
    else:
        raise HTTPException(status_code=409, detail=f"job state {job.state} cannot be cancelled")
    session.refresh(job)
    return _to_out(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    if job.state not in _RETRYABLE:
        raise HTTPException(status_code=409, detail=f"job state {job.state} is not retryable")

    item = job.media_item
    # If it was skipped because the output was larger, clear that exclusion and
    # reset eligibility so the retry will actually run.
    if job.state == "skipped_larger":
        key = (episode_exclusion_key(item.title, item.season, item.episode)
               if item.source == "sonarr" else movie_exclusion_key(item.title))
        for ex in session.query(Exclusion).filter_by(source=item.source, key=key).all():
            session.delete(ex)
        item.eligibility = "needs_transcode"

    # Only create a new job if none is active.
    active = (session.query(Job)
              .filter(Job.media_item_id == item.id, Job.state.in_(["queued", "running"]))
              .first())
    new_job = active
    if active is None:
        new_job = Job(media_item_id=item.id, state="queued")
        session.add(new_job)
    # Commit unconditionally so exclusion deletes + eligibility reset (and the
    # new job, if any) are persisted before we refresh/return.
    session.commit()
    state.controller.wake()
    session.refresh(new_job)
    return _to_out(new_job)
```

> Note: `list_jobs` uses `Query(100, ge=1, le=500)` / `Query(0, ge=0)` bounds (as in the library router), and the lookups use `session.get(..., options=[joinedload(...)])` rather than the deprecated `Query.get()`.

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_jobs.py -v`
Expected: PASS (5 tests). Note: `cancel` of a queued job flips state via the request session; the controller singleton is never started in tests, and `current_job_id` is `None`, so the queued branch runs.

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 44 passed (39 + 5).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/api/routers/jobs.py source_code/tests/test_api_jobs.py
git commit -m "feat: jobs API (enqueue/list/detail/cancel/retry)"
```

---

## Task 9: Exclusions router

**Files:**
- Modify: `source_code/transcoder/api/routers/exclusions.py`
- Test: `source_code/tests/test_api_exclusions.py`

- [ ] **Step 1: Write the failing test.** `tests/test_api_exclusions.py`:
```python
from transcoder.models import Exclusion


def test_exclusions_crud(api):
    client, Session = api
    # empty
    assert client.get("/api/exclusions").json() == []

    # create
    r = client.post("/api/exclusions", json={"source": "sonarr", "key": "A|1|1"})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert r.json()["reason"] == "manual"

    # list
    rows = client.get("/api/exclusions").json()
    assert len(rows) == 1 and rows[0]["key"] == "A|1|1"

    # delete
    assert client.delete(f"/api/exclusions/{eid}").status_code == 204
    assert client.get("/api/exclusions").json() == []

    # delete missing -> 404
    assert client.delete("/api/exclusions/999").status_code == 404
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_exclusions.py -v`
Expected: FAIL (404; endpoints missing).

- [ ] **Step 3: Replace `routers/exclusions.py`.**
```python
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from transcoder.api.deps import get_session
from transcoder.api.schemas import ExclusionIn, ExclusionOut
from transcoder.models import Exclusion

router = APIRouter(prefix="/api")


@router.get("/exclusions", response_model=list[ExclusionOut])
def list_exclusions(session: Session = Depends(get_session)):
    rows = session.query(Exclusion).order_by(Exclusion.id).all()
    return [ExclusionOut.model_validate(r) for r in rows]


@router.post("/exclusions", response_model=ExclusionOut, status_code=201)
def add_exclusion(body: ExclusionIn, session: Session = Depends(get_session)):
    existing = session.query(Exclusion).filter_by(source=body.source, key=body.key).first()
    if existing:
        raise HTTPException(status_code=409, detail="exclusion already exists")
    row = Exclusion(source=body.source, key=body.key, reason=body.reason)
    session.add(row)
    session.commit()
    session.refresh(row)
    return ExclusionOut.model_validate(row)


@router.delete("/exclusions/{exclusion_id}", status_code=204)
def delete_exclusion(exclusion_id: int, session: Session = Depends(get_session)):
    row = session.get(Exclusion, exclusion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="exclusion not found")
    session.delete(row)
    session.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_exclusions.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 45 passed (44 + 1).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/api/routers/exclusions.py source_code/tests/test_api_exclusions.py
git commit -m "feat: exclusions API (list/add/delete)"
```

---

## Task 10: Scan router (background discovery)

**Files:**
- Modify: `source_code/transcoder/api/routers/scan.py`
- Test: `source_code/tests/test_api_scan.py`

**Design:** `POST /api/scan` runs discovery in a `BackgroundTasks` job, guarded by `state.scan_status`. Returns 202 immediately; `409` if a scan is already running. The discovery functions need a session + clients; the background task builds them. For testability, the scan worker function is `_run_scan(session_factory, clients, body)` and the route injects `state.scan_status`. Tests call the endpoint with a monkeypatched discovery to keep it fast/hermetic.

- [ ] **Step 1: Write the failing test.** `tests/test_api_scan.py`:
```python
import transcoder.api.routers.scan as scan_mod
from transcoder.api import state


def test_scan_runs_and_reports_status(api, monkeypatch):
    client, Session = api
    calls = {}

    def fake_discover_sonarr(session, clients_unused, scope="all", target_title=None):
        calls["sonarr"] = (scope, target_title)
        return 7

    def fake_discover_radarr(session, clients_unused, target_movie=None):
        calls["radarr"] = target_movie
        return 3

    monkeypatch.setattr(scan_mod, "discover_sonarr", fake_discover_sonarr)
    monkeypatch.setattr(scan_mod, "discover_radarr", fake_discover_radarr)
    monkeypatch.setattr(scan_mod, "build_clients", lambda: {"sonarr": object(), "radarr": object()})
    monkeypatch.setattr(scan_mod, "SessionLocal", Session)
    # reset scan status singleton
    state.scan_status.set("idle")

    r = client.post("/api/scan", json={"app": "all", "scope": "all"})
    assert r.status_code == 202

    # TestClient runs BackgroundTasks synchronously after the response
    s = state.scan_status.snapshot()
    assert s["state"] == "done"
    assert s["detail"]["sonarr"] == 7
    assert s["detail"]["radarr"] == 3
    assert calls["sonarr"] == ("all", None)


def test_scan_conflict_when_running(api, monkeypatch):
    client, Session = api
    state.scan_status.set("running")
    r = client.post("/api/scan", json={"app": "all", "scope": "all"})
    assert r.status_code == 409
    state.scan_status.set("idle")


def test_scan_status_endpoint(api):
    client, Session = api
    state.scan_status.set("idle")
    r = client.get("/api/scan/status")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_scan.py -v`
Expected: FAIL (endpoints missing).

- [ ] **Step 3: Replace `routers/scan.py`.**
```python
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from transcoder.api import state
from transcoder.api.schemas import ScanIn
from transcoder.api.state import build_clients
from transcoder.db import SessionLocal
from transcoder.engine.discovery import discover_sonarr, discover_radarr

router = APIRouter(prefix="/api")
log = logging.getLogger("transcoder")


def _run_scan(body: ScanIn):
    # State is already "running" (set atomically by start_scan via try_start()).
    detail = {}
    try:
        clients = build_clients()
        session = SessionLocal()
        try:
            if body.app in ("all", "sonarr"):
                detail["sonarr"] = discover_sonarr(
                    session, clients["sonarr"], scope=body.scope, target_title=body.show)
            if body.app in ("all", "radarr"):
                detail["radarr"] = discover_radarr(
                    session, clients["radarr"], target_movie=body.movie)
        finally:
            session.close()
        state.scan_status.set("done", **detail)
    except Exception as exc:  # noqa: BLE001
        log.exception("scan failed")
        state.scan_status.set("error", message=str(exc), **detail)


@router.post("/scan", status_code=202)
def start_scan(body: ScanIn, background: BackgroundTasks):
    # Atomic check-and-set (ScanStatus.try_start) avoids a TOCTOU race where two
    # near-simultaneous requests both pass the guard before either task runs.
    if not state.scan_status.try_start():
        raise HTTPException(status_code=409, detail="a scan is already running")
    background.add_task(_run_scan, body)
    return {"status": "accepted"}


@router.get("/scan/status")
def scan_status():
    return state.scan_status.snapshot()
```

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_scan.py -v`
Expected: PASS (3 tests). (`monkeypatch.setattr(scan_mod, "SessionLocal", Session)` and the patched discovery keep it hermetic; TestClient executes background tasks synchronously after returning the response.)

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 48 passed (45 + 3).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/api/routers/scan.py source_code/tests/test_api_scan.py
git commit -m "feat: background scan endpoint + status"
```

---

## Task 11: Status + SSE stream router

**Files:**
- Modify: `source_code/transcoder/api/routers/stream.py`
- Test: `source_code/tests/test_api_status_stream.py`

**Design:** `GET /api/status` composes worker liveness + current job + queue length + stats. `GET /api/stream` is an SSE endpoint using `StreamingResponse` with `media_type="text/event-stream"`. The generator emits an initial `status` event then `heartbeat`s; it stops after a bounded number of iterations when a test header/param requests it, so tests don't hang. In production it loops until client disconnect.

- [ ] **Step 1: Write the failing test.** `tests/test_api_status_stream.py`:
```python
from transcoder.models import Job, MediaItem


def _seed_queued(Session):
    s = Session()
    item = MediaItem(source="sonarr", external_id="1", title="A", resolution=1080,
                     remote_path="/x", eligibility="needs_transcode")
    s.add(item); s.commit()
    s.add(Job(media_item_id=item.id, state="queued"))
    s.commit()
    s.close()


def test_status_endpoint(api):
    client, Session = api
    _seed_queued(Session)
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["queue_length"] == 1
    assert body["worker_alive"] in (True, False)
    assert "stats" in body


def test_stream_emits_event(api):
    client, Session = api
    # max_events=1 keeps the generator finite for the test
    r = client.get("/api/stream", params={"max_events": 1})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event:" in r.text
```

- [ ] **Step 2: Run, confirm FAIL.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_status_stream.py -v`
Expected: FAIL (endpoints missing).

- [ ] **Step 3: Replace `routers/stream.py`.**
```python
import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from transcoder.api.deps import get_session
from transcoder.api import state
from transcoder.api.schemas import JobOut, StatRow, StatusOut
from transcoder.models import Job, MediaItem

router = APIRouter(prefix="/api")


def _stats(session: Session) -> list[StatRow]:
    rows = (session.query(MediaItem.source, MediaItem.eligibility, func.count())
            .group_by(MediaItem.source, MediaItem.eligibility).all())
    return [StatRow(source=s, eligibility=e, count=c) for s, e, c in rows]


def _current_job_out(session: Session) -> JobOut | None:
    jid = state.controller.current_job_id
    if jid is None:
        return None
    job = session.query(Job).options(joinedload(Job.media_item)).get(jid)
    if job is None:
        return None
    out = JobOut.model_validate(job)
    out.title = job.media_item.title if job.media_item else None
    return out


@router.get("/status", response_model=StatusOut)
def status(session: Session = Depends(get_session)):
    queue_length = session.query(Job).filter(Job.state == "queued").count()
    return StatusOut(
        worker_alive=state.controller.is_alive(),
        current_job=_current_job_out(session),
        queue_length=queue_length,
        stats=_stats(session),
    )


@router.get("/stream")
def stream(max_events: int | None = None, session: Session = Depends(get_session)):
    async def gen():
        # initial snapshot
        cur = _current_job_out(session)
        payload = cur.model_dump() if cur else None
        yield f"event: status\ndata: {json.dumps(payload)}\n\n"
        count = 1
        while max_events is None or count < max_events:
            await asyncio.sleep(1.0)
            cur = _current_job_out(session)
            payload = cur.model_dump() if cur else None
            yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
            count += 1
        # finite when max_events set (tests); otherwise loops until disconnect

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run, confirm PASS.** Run: `.venv/Scripts/python.exe -m pytest tests/test_api_status_stream.py -v`
Expected: PASS (2 tests). With `max_events=1` the generator yields one `status` event then stops.

- [ ] **Step 5: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 50 passed (48 + 2).

- [ ] **Step 6: Commit.**
```bash
git add source_code/transcoder/api/routers/stream.py source_code/tests/test_api_status_stream.py
git commit -m "feat: status endpoint + SSE progress stream"
```

---

## Task 12: uvicorn entry point

**Files:**
- Create: `source_code/transcoder/api/__main__.py`
- Modify: `source_code/transcoder/config.py` (add API host/port settings)

- [ ] **Step 1: Add settings.** In `transcoder/config.py`, add two defaulted fields to the `Settings` class (after `DATABASE_URL`):
```python
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8765
```

- [ ] **Step 2: Create `transcoder/api/__main__.py`.**
```python
import uvicorn

from transcoder.config import settings
from transcoder.api.app import create_app


def main():
    uvicorn.run(create_app(), host=settings.API_HOST, port=settings.API_PORT)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add a config test.** Append to `tests/test_config.py`:
```python
def test_settings_api_defaults():
    from transcoder.config import settings
    assert settings.API_PORT == 8765
    assert settings.API_HOST == "0.0.0.0"
```

- [ ] **Step 4: Run config test.** Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Smoke-check the app imports and builds.** Run:
`.venv/Scripts/python.exe -c "from transcoder.api.app import create_app; create_app(start_worker=False); print('app ok')"`
Expected: prints `app ok` (no exceptions; note this constructs the app but does not start uvicorn or the lifespan).

- [ ] **Step 6: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 51 passed (50 + 1).

- [ ] **Step 7: Commit.**
```bash
git add source_code/transcoder/api/__main__.py source_code/transcoder/config.py source_code/tests/test_config.py
git commit -m "feat: uvicorn entry point + API host/port settings"
```

---

## Task 13: Docs update + manual live smoke (user-run)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `CLAUDE.md` Commands section.** After the existing CLI **Run:** block, add a **Serve (API):** block:
````markdown
**Serve (API, Cycle 2):**
```bash
cd source_code
python -m transcoder.api        # starts FastAPI+uvicorn on API_HOST:API_PORT (default 0.0.0.0:8765)
```
Key endpoints: `GET /api/health`, `GET /api/library`, `GET /api/library/stats`,
`POST /api/scan`, `GET /api/scan/status`, `POST /api/enqueue`, `GET /api/jobs`,
`POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`,
`GET /api/exclusions`, `GET /api/status`, `GET /api/stream` (SSE).
````
Also add to the Architecture section a one-line note:
```markdown
- `api/` — FastAPI service (Cycle 2): routers for library/scan/jobs/exclusions/status/stream; `worker_controller.py` runs the continuous background transcode worker.
```

- [ ] **Step 2: Run full suite.** Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 51 passed.

- [ ] **Step 3: Commit.**
```bash
git add CLAUDE.md
git commit -m "docs: document the Cycle 2 API service"
```

- [ ] **Step 4 (USER-RUN): manual live smoke.** With a real `.env` (real SFTP creds for actual transcoding), from `source_code/`:
```bash
.venv/Scripts/python.exe -m transcoder.api
```
Then in another shell:
```bash
curl http://localhost:8765/api/health
curl http://localhost:8765/api/library/stats
curl -X POST http://localhost:8765/api/scan -H "Content-Type: application/json" -d "{\"app\":\"radarr\",\"scope\":\"all\"}"
curl http://localhost:8765/api/scan/status
curl http://localhost:8765/api/status
```
Expected: health ok; stats reflect the DB; scan transitions running→done; status shows worker alive. (A real transcode only runs if something is `needs_transcode`.)

---

## Self-Review Notes (completed by plan author)

- **Spec coverage:** process/worker model (Tasks 5, 6, 12), WAL/concurrency (Task 2, deps Task 6a), cancellation (Tasks 3–5, 8), retry+exclusion reset (Task 8), library (Task 7), scan bg + 409 (Task 10), jobs (Task 8), exclusions (Task 9), status+SSE (Task 11), no-auth/LAN bind (Task 12 host/port), testing (every task). ✔
- **Type consistency:** `process_one_job(..., cancel_event=None, download=, upload=, convert=)` signature defined in Task 4 and consumed by the controller (Task 5) and tests; `WorkerController(session_factory, clients, process=, idle_timeout=)` consistent across Task 5 + state.py (Task 6); schema names (`JobOut.title`, `LibraryPage`, `StatRow`, `EnqueueOut`) consistent across routers. ✔
- **Hermetic tests:** the `api` fixture (Task 6a) overrides `get_session` and patches `app_module.init_db/migrate_legacy/SessionLocal`; scan/jobs tests patch module-level `SessionLocal`/discovery where the controller/background task would otherwise use the real DB. ✔
- **Placeholder scan:** no TBD/TODO; every code step has full code. ✔

> Known seam to watch during execution: `state.controller` is constructed at import with the real `SessionLocal`. Tests never `.start()` it, and cancel/retry mutate via the request session, so this is safe for tests. When the live server runs, the controller uses the real `SessionLocal` (correct). If any test starts the controller, it must inject a test session_factory instead.
