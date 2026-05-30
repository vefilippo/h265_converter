# Job Phases, Live Progress & Per-Job Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show per-phase job status (Downloading/Transcoding/Uploading) with a live progress bar in every phase, and let the user read a job's own logs from its detail dialog.

**Architecture:** Add `phase` and `log` columns to `Job` (keep `state` values unchanged). The worker sets `phase` at each step, streams real byte-progress from SFTP into `job.progress`, and appends timestamped lines to `job.log`. A new `GET /api/jobs/{id}/logs` endpoint serves the log; `JobOut` gains `phase` so the existing `/status` + `/stream` carry it to the UI. The frontend renders the phase as the badge label and adds a Logs section to the detail dialog.

**Tech Stack:** Python 3.10, SQLAlchemy 2.0, FastAPI, paramiko (SFTP), pytest; React 18 + TypeScript + Vite + TanStack Query + Vitest.

**Conventions for every task:**
- Run backend tests with the venv interpreter: `./.venv/Scripts/python.exe -m pytest` from `source_code/`.
- Run frontend tooling from `source_code/web/`: `npx vitest run`, `npx tsc --noEmit`, `npm run build`.
- Commit message footer line: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- The test `session` fixture builds tables from model metadata, so new model columns appear automatically in tests (no migration needed there).

---

## File Structure

- `source_code/transcoder/models.py` — add `phase`, `log` to `Job`; drop `log_excerpt` from the ORM.
- `source_code/transcoder/db.py` — `ensure_job_columns()` idempotent ALTER for the existing prod DB.
- `source_code/transcoder/api/app.py` — call `ensure_job_columns()` in lifespan.
- `source_code/transcoder/sftp_client.py` — optional `progress_cb` param on upload/download.
- `source_code/transcoder/engine/worker.py` — phase transitions, `job_log`, throttled progress, raise on SFTP failure.
- `source_code/transcoder/api/schemas.py` — `JobOut.phase`, new `JobLogOut`.
- `source_code/transcoder/api/routers/jobs.py` — `GET /api/jobs/{id}/logs`.
- `source_code/web/src/api/types.ts` — `Job.phase`, `JobLog`.
- `source_code/web/src/hooks/queries.ts` — `useJobLogs`.
- `source_code/web/src/components/ui/badge.tsx` — phase variants.
- `source_code/web/src/pages/Jobs.tsx` — phase label + logs section.
- `source_code/web/src/pages/Dashboard.tsx` — phase label on current-job card.
- Tests: `source_code/tests/test_worker.py`, `test_sftp_progress.py` (new), `test_api_jobs.py`; `web/src/pages/Jobs.test.tsx`.

---

### Task 1: Add `phase` and `log` columns to the Job model

**Files:**
- Modify: `source_code/transcoder/models.py`
- Test: `source_code/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `source_code/tests/test_models.py`:

```python
def test_job_has_phase_and_log_columns(session):
    from transcoder.models import Job, MediaItem
    item = MediaItem(source="sonarr", external_id="1", title="A", season=1,
                     episode=1, remote_path="/x", resolution=1080,
                     eligibility="needs_transcode")
    session.add(item); session.commit()
    job = Job(media_item_id=item.id, state="running", phase="downloading", log="hi")
    session.add(job); session.commit()
    fetched = session.query(Job).one()
    assert fetched.phase == "downloading"
    assert fetched.log == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_models.py::test_job_has_phase_and_log_columns -v`
Expected: FAIL with `TypeError: 'phase' is an invalid keyword argument for Job` (or similar).

- [ ] **Step 3: Implement the columns**

In `source_code/transcoder/models.py`, in `class Job`, replace the line:

```python
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
```

with:

```python
    phase: Mapped[str | None] = mapped_column(String(16), nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_models.py::test_job_has_phase_and_log_columns -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite (catch `log_excerpt` references)**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass. If anything references `log_excerpt`, update it to `log`.

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/models.py source_code/tests/test_models.py
git commit -m "feat: add phase and log columns to Job (replace log_excerpt)"
```

---

### Task 2: Idempotent column migration for the existing production DB

The test DB is built from model metadata, but the existing `transcoder.db` has a
real `job` table without the new columns. `create_all` won't alter it, so add an
idempotent ALTER and call it on startup.

**Files:**
- Modify: `source_code/transcoder/db.py`
- Modify: `source_code/transcoder/api/app.py`
- Test: `source_code/tests/test_db_migrate_columns.py` (create)

- [ ] **Step 1: Write the failing test**

Create `source_code/tests/test_db_migrate_columns.py`:

```python
from sqlalchemy import create_engine, text


def test_ensure_job_columns_adds_missing_and_copies_log_excerpt():
    from transcoder.db import ensure_job_columns
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        # Simulate an OLD schema: job with log_excerpt, no phase/log.
        conn.execute(text(
            "CREATE TABLE job (id INTEGER PRIMARY KEY, state VARCHAR, "
            "log_excerpt TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO job (id, state, log_excerpt) VALUES (1, 'done', 'old line')"
        ))

    ensure_job_columns(eng)

    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(job)"))}
        assert "phase" in cols and "log" in cols
        row = conn.execute(text("SELECT log FROM job WHERE id=1")).one()
        assert row[0] == "old line"

    # Idempotent: a second call must not raise.
    ensure_job_columns(eng)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_db_migrate_columns.py -v`
Expected: FAIL with `ImportError: cannot import name 'ensure_job_columns'`.

- [ ] **Step 3: Implement `ensure_job_columns`**

Append to `source_code/transcoder/db.py`:

```python
from sqlalchemy import text


def ensure_job_columns(engine=None):
    """Idempotently add the job.phase / job.log columns to an existing DB and
    copy any legacy log_excerpt content into log. No-op when already present or
    when the job table doesn't exist yet (fresh DBs get the columns via
    create_all)."""
    eng = engine or make_engine()
    with eng.begin() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "job" not in tables:
            return
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(job)"))}
        if "phase" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN phase VARCHAR(16)"))
        if "log" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN log TEXT"))
            if "log_excerpt" in cols:
                conn.execute(text(
                    "UPDATE job SET log = log_excerpt "
                    "WHERE log IS NULL AND log_excerpt IS NOT NULL"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_db_migrate_columns.py -v`
Expected: PASS

- [ ] **Step 5: Wire into the app lifespan**

In `source_code/transcoder/api/app.py`, change the import:

```python
from transcoder.db import SessionLocal, init_db
```

to:

```python
from transcoder.db import SessionLocal, init_db, ensure_job_columns
```

Then in `lifespan`, immediately after `init_db()`, add:

```python
        init_db()
        ensure_job_columns()
```

- [ ] **Step 6: Verify app still builds and full suite passes**

Run: `./.venv/Scripts/python.exe -c "from transcoder.api.app import create_app; create_app(start_worker=False); print('ok')"`
Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: prints `ok`; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add source_code/transcoder/db.py source_code/transcoder/api/app.py source_code/tests/test_db_migrate_columns.py
git commit -m "feat: idempotent job.phase/job.log column migration on startup"
```

---

### Task 3: SFTP client — optional `progress_cb` percent callback

**Files:**
- Modify: `source_code/transcoder/sftp_client.py`
- Test: `source_code/tests/test_sftp_progress.py` (create)

- [ ] **Step 1: Write the failing test**

Create `source_code/tests/test_sftp_progress.py`:

```python
import transcoder.sftp_client as sftp


class _FakeSFTP:
    def __init__(self, size): self._size = size
    def stat(self, remote):
        class S: st_size = self._size
        return S()
    def get(self, remote, local, callback=None):
        callback(0, self._size); callback(self._size // 2, self._size)
        callback(self._size, self._size)
    def put(self, local, remote, callback=None):
        callback(self._size, self._size)
    def close(self): pass


class _FakeTransport:
    def __init__(self, *a, **k): pass
    def connect(self, **k): pass
    def close(self): pass


def test_download_progress_cb_receives_percent(monkeypatch, tmp_path):
    monkeypatch.setattr(sftp.paramiko, "Transport", _FakeTransport)
    monkeypatch.setattr(sftp.paramiko.SFTPClient, "from_transport",
                        staticmethod(lambda t: _FakeSFTP(100)))
    monkeypatch.setattr(sftp.Path, "mkdir", lambda *a, **k: None)
    seen = []
    res = sftp.download_file_via_sftp(
        "h", 22, "u", "p", "/r/a.mkv", str(tmp_path / "a.mkv"),
        progress_cb=seen.append)
    assert res["success"] is True
    assert seen[-1] == 100 and 50 in seen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_sftp_progress.py -v`
Expected: FAIL with `TypeError: download_file_via_sftp() got an unexpected keyword argument 'progress_cb'`.

- [ ] **Step 3: Add the param to both functions**

In `source_code/transcoder/sftp_client.py`, change the `upload_file_via_sftp`
signature to:

```python
def upload_file_via_sftp(host, port, username, password,
                         local_path, remote_path, progress_cb=None) -> dict:
```

and inside its `progress_callback`, after `progress_bar.refresh()`:

```python
        def progress_callback(transferred, total):
            progress_bar.n = transferred
            progress_bar.refresh()
            if progress_cb is not None and total:
                progress_cb(int(transferred / total * 100))
```

Change the `download_file_via_sftp` signature to:

```python
def download_file_via_sftp(host, port, username, password,
                           remote_path, local_path, progress_cb=None) -> dict:
```

and apply the identical `progress_cb` addition inside its `progress_callback`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_sftp_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/sftp_client.py source_code/tests/test_sftp_progress.py
git commit -m "feat: optional progress_cb percent callback on SFTP transfers"
```

---

### Task 4: Worker — phase transitions, job_log, throttled progress, raise on SFTP failure

**Files:**
- Modify: `source_code/transcoder/engine/worker.py`
- Test: `source_code/tests/test_worker.py`

- [ ] **Step 1: Write the failing tests**

The existing `_make_io` in `tests/test_worker.py` returns `download`/`upload`
that ignore extra kwargs and return `{"success": True}`. Update `_make_io` so
the fakes accept `progress_cb` and record phases, and add new tests. Replace the
`download` and `upload` inner functions in `_make_io` with:

```python
    def download(host, port, user, pw, remote, local, progress_cb=None):
        calls["download"].append((remote, local))
        calls.setdefault("phase_at_download", []).append(_current_phase[0])
        if progress_cb: progress_cb(100)
        return {"success": True} if not fail_download else {"success": False, "message": "boom"}

    def upload(host, port, user, pw, local, remote, progress_cb=None):
        calls["upload"].append((local, remote))
        calls.setdefault("phase_at_upload", []).append(_current_phase[0])
        if progress_cb: progress_cb(100)
        return {"success": True}
```

At the top of `_make_io` add a `fail_download=False` parameter and a phase
tracker that reads the job; simplest approach — capture phase via a closure that
the test sets. Since `_make_io` has no job handle, instead assert phase by
inspecting `job.phase` transitions through a recording convert. Use this revised
`_make_io` signature and body:

```python
def _make_io(smaller=True, fail=False, fail_download=False):
    calls = {"download": [], "upload": [], "removed": [], "phases": []}

    def download(host, port, user, pw, remote, local, progress_cb=None):
        calls["download"].append((remote, local))
        if progress_cb: progress_cb(100)
        return {"success": True} if not fail_download else {"success": False, "message": "dl boom"}

    def upload(host, port, user, pw, local, remote, progress_cb=None):
        calls["upload"].append((local, remote))
        if progress_cb: progress_cb(100)
        return {"success": True}

    def convert(inp, out, preset, progress_cb=None, cancel_event=None):
        if progress_cb: progress_cb(50)
        if fail:
            return None, False
        path = os.path.join(".", "tmp_out.mkv")
        with open(path, "wb") as f:
            f.write(b"x" * (10 if smaller else 5000))
        return path, (not smaller)

    return calls, download, upload, convert
```

Add these tests at the end of `tests/test_worker.py`:

```python
def test_worker_sets_and_clears_phase(session, monkeypatch):
    item = _seed(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job); session.commit()
    monkeypatch.setattr("transcoder.engine.worker.settings.OUTPUT_FOLDER", "./")
    monkeypatch.setattr("transcoder.engine.worker.os.path.getsize", lambda p: 10)
    monkeypatch.setattr("transcoder.engine.worker.os.makedirs", lambda *a, **k: None)
    monkeypatch.setattr("transcoder.engine.worker.os.path.exists", lambda p: False)
    calls = _make_io(smaller=True)
    process_one_job(session, job, {"sonarr": object()}, **_io_kwargs(calls))
    assert job.state == "done"
    assert job.phase is None  # cleared on terminal state
    assert job.log and "Downloading" in job.log and "Transcoding" in job.log and "Uploading" in job.log


def test_worker_download_failure_marks_failed(session, monkeypatch):
    item = _seed(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job); session.commit()
    monkeypatch.setattr("transcoder.engine.worker.settings.OUTPUT_FOLDER", "./")
    monkeypatch.setattr("transcoder.engine.worker.os.path.getsize", lambda p: 10)
    monkeypatch.setattr("transcoder.engine.worker.os.makedirs", lambda *a, **k: None)
    monkeypatch.setattr("transcoder.engine.worker.os.path.exists", lambda p: False)
    calls = _make_io(smaller=True, fail_download=True)
    process_one_job(session, job, {"sonarr": object()}, **_io_kwargs(calls))
    assert job.state == "failed"
    assert job.phase is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_worker.py -q`
Expected: the two new tests FAIL (no `phase`/`log` behavior; download failure currently ignored → job would be `done`).

- [ ] **Step 3: Implement phase + logging + progress + raise in the worker**

In `source_code/transcoder/engine/worker.py`, add a helper near the top (after
`log = logging.getLogger("transcoder")`):

```python
import datetime as _dt


def job_log(session, job, msg):
    """Append a timestamped line to job.log and emit to the global logger."""
    stamp = _dt.datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    job.log = (job.log + "\n" + line) if job.log else line
    log.info("Job %s: %s", job.id, msg)


def _progress_writer(session, job):
    """Return a progress_cb that commits only when the integer percent changes,
    so per-chunk SFTP callbacks don't hammer SQLite."""
    last = {"pct": -1}
    def cb(pct):
        pct = int(pct)
        if pct != last["pct"]:
            last["pct"] = pct
            job.progress = pct
            session.commit()
    return cb
```

Then rewrite the body of `process_one_job` between the initial `job.state =
"running"` block and the HandBrake call so each step sets `phase`, logs, and
passes a progress writer. Replace the existing download section:

```python
        job.state = "running"
        job.phase = "downloading"
        job.started_at = utcnow()
        job.progress = 0
        job.preset = settings.PRESET_4K if item.resolution > 1080 else settings.PRESET_1080
        session.commit()
        job_log(session, job, f"Downloading {item.title}")

        os.makedirs("./tmp", exist_ok=True)
        file_path = _local_path(item)
        tmp_file = os.path.join("./tmp", os.path.basename(file_path))
        dl = download(settings.SFTP_HOST, settings.SFTP_PORT, settings.SFTP_USERNAME,
                      settings.SFTP_PASSWORD, file_path, tmp_file,
                      progress_cb=_progress_writer(session, job))
        if isinstance(dl, dict) and dl.get("success") is False:
            raise RuntimeError(f"download failed: {dl.get('message')}")

        original_size = os.path.getsize(tmp_file)
        out_name = _output_name(item)

        job.phase = "transcoding"
        job.progress = 0
        session.commit()
        job_log(session, job, f"Transcoding {item.title} (preset {job.preset})")
        output_file, exclude_flag = convert(tmp_file, out_name, job.preset,
                                            progress_cb=_progress_writer(session, job),
                                            cancel_event=cancel_event)
```

(Delete the old `def cb(pct): ... session.commit()` local and the old
`log.info("Job %s: downloading ...")` / `transcoding` lines it replaces.)

In the upload branch (the `else` of `if exclude_flag`), set the phase and pass a
progress writer, and raise on failure:

```python
        else:
            job.phase = "uploading"
            job.progress = 0
            session.commit()
            job_log(session, job, f"Uploading {out_name}")
            up = upload(settings.SFTP_HOST, settings.SFTP_PORT, settings.SFTP_USERNAME,
                        settings.SFTP_PASSWORD, output_file, settings.WATCH_FOLDER + out_name,
                        progress_cb=_progress_writer(session, job))
            if isinstance(up, dict) and up.get("success") is False:
                raise RuntimeError(f"upload failed: {up.get('message')}")
            client.manual_import_one(output_file)
            item.eligibility = "already_h265"
            job.output_filename = out_name
            job.state = "done"
            job_log(session, job, f"Done {item.title} ({job.reduction_pct or 0.0:.1f}% smaller)")
```

Clear `phase` on every terminal path. At the start of the success commit, the
skip branch, and each `except` block, set `job.phase = None` before the final
`session.commit()`. Concretely:
- In the `if exclude_flag:` branch add `job.phase = None` before its state set and `job_log(session, job, "Skipped (output larger)")`.
- Before `job.finished_at = utcnow(); session.commit()` at the end of the try, add `job.phase = None`.
- In `except TranscodeCancelled`, `except Exception`, and the HandBrake-`None`
  failure block, add `job.phase = None` before their `session.commit()`, and add
  `job_log(session, job, "...")` lines (`"Cancelled"`, `f"Failed: {exc}"`,
  `"HandBrake failed"` respectively).

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_worker.py -q`
Expected: all pass (including the two new tests and the existing
success/larger/convert-failure/cleanup tests).

- [ ] **Step 5: Run the full backend suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/engine/worker.py source_code/tests/test_worker.py
git commit -m "feat: worker sets job phase, per-job log, live SFTP progress; fail on transfer error"
```

---

### Task 5: Schema + API — `JobOut.phase`, `JobLogOut`, `GET /api/jobs/{id}/logs`

**Files:**
- Modify: `source_code/transcoder/api/schemas.py`
- Modify: `source_code/transcoder/api/routers/jobs.py`
- Test: `source_code/tests/test_api_jobs.py`

- [ ] **Step 1: Write the failing tests**

Add to `source_code/tests/test_api_jobs.py`:

```python
def test_jobs_list_includes_phase(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="running", phase="transcoding"))
    s.commit(); s.close()
    body = client.get("/api/jobs").json()
    assert body["items"][0]["phase"] == "transcoding"


def test_job_logs_endpoint_returns_log(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="done", log="line one\nline two"))
    s.commit(); jid = s.query(Job).one().id; s.close()
    r = client.get(f"/api/jobs/{jid}/logs")
    assert r.status_code == 200
    assert r.json()["log"] == "line one\nline two"


def test_job_logs_endpoint_404(api):
    client, _ = api
    assert client.get("/api/jobs/999/logs").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_api_jobs.py -k "phase or logs" -v`
Expected: FAIL (no `phase` field; `/logs` route 404 for an existing job or missing).

- [ ] **Step 3: Implement schema additions**

In `source_code/transcoder/api/schemas.py`, add `phase` to `JobOut` (after
`title`):

```python
    phase: str | None = None
```

and add a new model after `JobPage`:

```python
class JobLogOut(BaseModel):
    log: str
```

- [ ] **Step 4: Implement the logs endpoint**

In `source_code/transcoder/api/routers/jobs.py`, update the schema import:

```python
from transcoder.api.schemas import EnqueueIn, EnqueueOut, JobOut, JobPage, JobLogOut
```

and add the route after `get_job`:

```python
@router.get("/jobs/{job_id}/logs", response_model=JobLogOut)
def get_job_logs(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    return JobLogOut(log=job.log or "")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_api_jobs.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/api/schemas.py source_code/transcoder/api/routers/jobs.py source_code/tests/test_api_jobs.py
git commit -m "feat: JobOut.phase + GET /api/jobs/{id}/logs endpoint"
```

---

### Task 6: Frontend types + `useJobLogs` hook

**Files:**
- Modify: `source_code/web/src/api/types.ts`
- Modify: `source_code/web/src/hooks/queries.ts`

- [ ] **Step 1: Add the types**

In `source_code/web/src/api/types.ts`, add `phase` to `Job` (after `title`):

```ts
  phase: string | null;
```

and add:

```ts
export interface JobLog { log: string; }
```

- [ ] **Step 2: Add the hook**

In `source_code/web/src/hooks/queries.ts`, after `useJobs`, add (the existing
file imports `useQuery` and `api`; add `JobLog` to the type import from
`../api/types`):

```ts
export const useJobLogs = (id: number, live: boolean) =>
  useQuery({
    queryKey: ["jobLogs", id],
    queryFn: () => api.get<JobLog>(`/api/jobs/${id}/logs`),
    refetchInterval: live ? 2000 : false,
  });
```

- [ ] **Step 3: Typecheck**

Run (from `source_code/web`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add source_code/web/src/api/types.ts source_code/web/src/hooks/queries.ts
git commit -m "feat: web Job.phase type + useJobLogs hook"
```

---

### Task 7: Frontend badge phase label + variants

**Files:**
- Modify: `source_code/web/src/components/ui/badge.tsx`
- Test: `source_code/web/src/components/ui/ui.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `source_code/web/src/components/ui/ui.test.tsx` (it already renders UI
primitives; follow its existing import style):

```ts
import { jobStateLabel } from "./badge";

test("jobStateLabel shows the phase for a running job", () => {
  expect(jobStateLabel({ state: "running", phase: "transcoding" } as any)).toBe("Transcoding");
  expect(jobStateLabel({ state: "running", phase: null } as any)).toBe("running");
  expect(jobStateLabel({ state: "done", phase: null } as any)).toBe("done");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `source_code/web`): `npx vitest run src/components/ui/ui.test.tsx`
Expected: FAIL — `jobStateLabel` is not exported.

- [ ] **Step 3: Implement label helper + phase variants**

`badge.tsx` defines variants via `cva(...)` — a `variant: { ... }` object inside
`badgeVariants`. Add three keys to that object (alongside `queued`, `running`,
etc.):

```ts
        downloading: "bg-cyan-500/15 text-cyan-400",
        transcoding: "bg-amber-500/15 text-amber-400",
        uploading: "bg-teal-500/15 text-teal-400",
```

`BadgeVariant` is derived from the cva variants via
`NonNullable<VariantProps<typeof badgeVariants>["variant"]>`, so the new keys
are valid automatically — no union to edit.

Extend `jobStateVariant` to map phases — add these cases before `default:`:

```ts
    case "downloading": return "downloading";
    case "transcoding": return "transcoding";
    case "uploading": return "uploading";
```

Add and export the label helper (place after `jobStateVariant`):

```ts
export function jobStateLabel(job: { state: string; phase: string | null }): string {
  if (job.state === "running" && job.phase) {
    return job.phase.charAt(0).toUpperCase() + job.phase.slice(1);
  }
  return job.state;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `source_code/web`): `npx vitest run src/components/ui/ui.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add source_code/web/src/components/ui/badge.tsx source_code/web/src/components/ui/ui.test.tsx
git commit -m "feat: badge phase variants + jobStateLabel helper"
```

---

### Task 8: Jobs page — phase label, phase-aware progress, logs section; Dashboard label

**Files:**
- Modify: `source_code/web/src/pages/Jobs.tsx`
- Modify: `source_code/web/src/pages/Dashboard.tsx`
- Test: `source_code/web/src/pages/Jobs.test.tsx`

- [ ] **Step 1: Write the failing tests**

In `source_code/web/src/pages/Jobs.test.tsx`, add `phase` to the running item in
`ITEMS` (the queued item id 1 → set `state: "running", phase: "transcoding"` OR
add a third item; simplest: change item 1 to running+transcoding and update its
existing assertions if needed). Add a `/api/jobs/{id}/logs` branch to
`makeFetch` returning `{ log: "hello log" }`, and add:

```ts
test("running job shows the phase label", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  expect(await screen.findByText("Transcoding")).toBeInTheDocument();
});

test("opening details shows the job log", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  await screen.findByText(/Movie X/);
  const rows = screen.getAllByRole("row");
  const movieRow = rows.find((r) => r.textContent?.includes("Movie X"));
  fireEvent.click(within(movieRow!).getByRole("button", { name: /details/i }));
  expect(await screen.findByText("hello log")).toBeInTheDocument();
});
```

Add the fetch branch inside `makeFetch` before the generic `/api/jobs` branch:

```ts
    if (/\/api\/jobs\/\d+\/logs/.test(url)) {
      return new Response(JSON.stringify({ log: "hello log" }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `source_code/web`): `npx vitest run src/pages/Jobs.test.tsx`
Expected: FAIL — no "Transcoding" label; details dialog has no log section.

- [ ] **Step 3: Use the label + render the State/Progress columns by phase**

In `source_code/web/src/pages/Jobs.tsx`, import the helper and the hook:

```ts
import { Badge, jobStateVariant, jobStateLabel } from "../components/ui/badge";
import { useActions, useJobs, useJobLogs } from "../hooks/queries";
```

In the table row, replace both badge renderings that show `{job.state}` with the
label, e.g. the State cell:

```tsx
                  <TD>
                    <Badge variant={jobStateVariant(job.phase && job.state === "running" ? job.phase : job.state)}>
                      {jobStateLabel(job)}
                    </Badge>
                  </TD>
```

and in the Progress cell, change the running check to keep showing the bar (it
already keys on `job.state === "running"`; no change needed) but use the label in
its fallback badge the same way.

- [ ] **Step 4: Add the Logs section to `JobDetailDialog`**

In `source_code/web/src/pages/Jobs.tsx`, change `JobDetailDialog` to fetch logs.
Replace its signature/body opening with:

```tsx
function JobDetailDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const live = job.state === "running";
  const { data: logs } = useJobLogs(job.id, live);
  return (
    <Dialog open onClose={onClose} title={job.title ?? `Job #${job.id}`}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
```

and just before the closing `</Dialog>` (after the `</dl>`), add:

```tsx
      <div className="mt-4">
        <div className="text-muted text-sm mb-1">Logs</div>
        <pre className="bg-surface rounded-md p-3 text-xs font-mono max-h-64 overflow-auto whitespace-pre-wrap">
          {logs?.log ? logs.log : "No logs yet"}
        </pre>
      </div>
```

- [ ] **Step 5: Dashboard current-job label**

In `source_code/web/src/pages/Dashboard.tsx`, import `jobStateLabel`:

```ts
import { Badge, jobStateVariant, jobStateLabel } from "../components/ui/badge";
```

In the "Current Job" card, replace the badge content `{currentJob.state}` with
`{jobStateLabel(currentJob)}` and its variant arg with
`jobStateVariant(currentJob.phase && currentJob.state === "running" ? currentJob.phase : currentJob.state)`.

- [ ] **Step 6: Run tests, typecheck, build**

Run (from `source_code/web`):
- `npx vitest run` → all pass
- `npx tsc --noEmit` → no errors
- `npm run build` → succeeds

- [ ] **Step 7: Commit**

```bash
git add source_code/web/src/pages/Jobs.tsx source_code/web/src/pages/Dashboard.tsx source_code/web/src/pages/Jobs.test.tsx
git commit -m "feat: Jobs/Dashboard show phase label + per-job logs in detail dialog"
```

---

### Task 9: Final verification + docs

**Files:**
- Modify: `CLAUDE.md` (endpoint list)

- [ ] **Step 1: Full backend suite**

Run (from `source_code`): `./.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Full frontend suite + build**

Run (from `source_code/web`): `npx vitest run && npx tsc --noEmit && npm run build`
Expected: all pass, clean build.

- [ ] **Step 3: Document the new endpoint**

In `CLAUDE.md`, in the "Key endpoints" list, add `GET /api/jobs/{id}/logs` next
to the other job endpoints.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note GET /api/jobs/{id}/logs and job phases in CLAUDE.md"
```

- [ ] **Step 5: Finish the branch**

Use superpowers:finishing-a-development-branch to merge to `master`.

---

## Self-Review

**Spec coverage:**
- Data model (phase + log, repurpose log_excerpt) → Task 1 + Task 2. ✓
- Worker phase transitions, job_log, throttled progress, SFTP raise-on-failure → Task 4. ✓
- SFTP byte-progress plumbing → Task 3 + Task 4. ✓
- JobOut.phase + GET /api/jobs/{id}/logs → Task 5. ✓
- Frontend types/hook → Task 6; badge label/variants → Task 7; detail dialog logs + Dashboard label + phase progress → Task 8. ✓
- Testing across backend + frontend → embedded per task + Task 9. ✓

**Type consistency:** `phase` (str|None) and `log` (Text) consistent across model, migration, schema, types. `jobStateLabel(job)` signature consistent in Tasks 7 & 8. `useJobLogs(id, live)` consistent in Tasks 6 & 8. `JobLogOut {log}` ↔ `JobLog {log}` ↔ `/logs` response consistent across Tasks 5, 6, 8.

**Placeholder scan:** No TBD/TODO; all code blocks concrete.

**Note for implementer:** `test_worker.py` already monkeypatches `os.path.exists`/`getsize`; the new download/upload fakes take `progress_cb=None` so they stay compatible. Confirm no other caller of the SFTP functions breaks — the only callers are the worker (updated) and tests.
