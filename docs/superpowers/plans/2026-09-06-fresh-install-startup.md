# Fresh-Install Startup Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the installed app actually start on a clean machine, and make any failure to start visible instead of silently showing whatever else owns the port.

**Architecture:** Three independent changes. (1) Stop querying the database at module-import time, which is the actual blocker — it runs before `init_db()` and dies on a fresh install. (2) Refuse to start when the configured port is already taken, naming the occupant. (3) Make the tray wait for the server and report failure, instead of opening a browser regardless.

**Tech Stack:** Python 3.14 / FastAPI / uvicorn / SQLAlchemy / pytest; pystray + winotify tray launcher.

**Spec:** none — this is a defect report. Evidence is in this document.

## The evidence

A real install on 2026-09-06 produced `log/server_start.log`:

```
sqlite3.OperationalError: no such table: setting
  File "...\transcoder\api\__main__.py", line 4, in <module>
    from transcoder.api.app import create_app
  File "...\transcoder\api\app.py", line 13, in <module>
    from transcoder.api import state
  File "...\transcoder\api\state.py", line 79, in <module>
    controller = WorkerController(SessionLocal, build_clients())
  File "...\transcoder\api\state.py", line 17, in build_clients
    get_effective(db, "sonarr_url", settings.SONARR_URL),
```

`state.py:79` constructs its singletons at import. `build_clients()` reads the `setting` table. `app.py:13` imports `state` at module scope, so this happens before `create_app()` and therefore before the lifespan calls `init_db()`. On a fresh install there are no tables, the process dies, and nothing ever binds.

It is invisible in development because the dev `transcoder.db` already has its tables from earlier runs. It is invisible to the user because the tray launches the server with `pythonw.exe` (no console) and then opens a browser regardless — which, with something else on port 8765, showed an unrelated application's UI.

## Global Constraints

- **Backend tests:** `python -m pytest` from the **repo root** (`pytest.ini` sets `pythonpath = solution`). Never `cd solution` to run pytest.
- **Frontend tests:** `npm test` from `solution/web`.
- **Baseline:** backend 317 passed / 1 skipped / 1 warning; frontend 19 files / 83 tests.
- **TDD is mandatory** (CLAUDE.md): failing test first.
- The app is launched with cwd = `solution/` and reads a cwd-relative `transcoder.db`.
- `API_HOST` / `API_PORT` come from `transcoder.config.settings` (default `0.0.0.0` / `8765`).
- **Do not change** the existing `WorkerController(session_factory, clients_dict, ...)` calling convention — tests across the suite pass a plain dict.
- Workers: never run `git checkout`, `git restore`, `git stash`, `git reset`, `git clean`, `git add` or `git commit`.

---

### Task 1: Stop touching the database at import time

**This is the blocker.** Everything else is diagnostics.

**Files:**
- Modify: `solution/transcoder/api/state.py`, `solution/transcoder/worker_controller.py`
- Test: `tests/test_fresh_install_boot.py` (create)

**Interfaces:**
- Produces: `WorkerController` accepts either a clients dict (as today) or a zero-argument callable returning one, resolved on first use.

- [ ] **Step 1: Write the failing test**

The honest reproduction is a subprocess against a genuinely empty database — an in-process test cannot un-import `state`, and that import is the thing under test.

```python
import subprocess, sys, textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOLUTION = REPO_ROOT / "solution"


def test_app_imports_and_builds_against_an_empty_database(tmp_path):
    """A fresh install has a database file with NO tables. Importing the API
    must not query one. This died with 'no such table: setting' in the field:
    state.py built its singletons at import, before init_db() had ever run."""
    db = tmp_path / "transcoder.db"
    db.touch()                      # exists, but contains no tables
    script = textwrap.dedent("""
        from transcoder.api.app import create_app
        create_app(start_worker=False)
        print("OK")
    """)
    env = {
        "DATABASE_URL": f"sqlite:///{db.as_posix()}",
        "PYTHONPATH": str(SOLUTION),
    }
    import os
    full_env = {**os.environ, **env}
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path, env=full_env,
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no such table" not in (proc.stdout + proc.stderr)
```

Confirm how config reads the DB URL before relying on `DATABASE_URL`; if the env var name differs, use the real one. If `create_app` does not take `start_worker`, read its signature and adapt.

- [ ] **Step 2: Run it and watch it fail**

Run: `python -m pytest tests/test_fresh_install_boot.py -v`
Expected: FAIL, with `no such table: setting` in the captured output. **If it passes, stop** — the reproduction is wrong and the rest of the task is built on sand.

- [ ] **Step 3: Make the clients lazy**

In `solution/transcoder/worker_controller.py`, resolve the clients on first use rather than storing whatever was passed:

```python
    @property
    def clients(self) -> dict:
        """Resolved on first use. state.py passes the FACTORY, not a dict, so
        that importing the API never opens the database -- on a fresh install
        the tables do not exist until the lifespan runs init_db()."""
        if callable(self._clients):
            self._clients = self._clients()
        return self._clients
```

Replace every internal read of `self._clients` with `self.clients`. Leave the constructor signature alone; a dict still works exactly as before.

In `solution/transcoder/api/state.py`, pass the function instead of calling it:

```python
# Pass build_clients itself, NOT build_clients(): this module is imported at
# app import time, before the lifespan has run init_db(), so a fresh install
# has no tables yet.
controller = WorkerController(SessionLocal, build_clients)
```

- [ ] **Step 4: Verify**

Run: `python -m pytest -q` from the repo root.
Expected: green, count up by 1 (baseline 317).

Then grep for any other module-scope database access on the import path — `state.py` may not be the only one. Report what you find; do not fix anything outside the two files without saying so.

- [ ] **Step 5: Report (do not commit)**

---

### Task 2: Refuse to start on an occupied port

**Files:**
- Modify: `solution/transcoder/api/__main__.py`
- Test: `tests/test_api_main_port_check.py` (create)

**Interfaces:**
- Produces: a `port_is_free(host, port) -> bool` helper (or similar) in `transcoder/api/__main__.py`, importable by tests.

Current contents of that file:

```python
import uvicorn

from transcoder.config import settings
from transcoder.api.app import create_app


def main():
    uvicorn.run(create_app(), host=settings.API_HOST, port=settings.API_PORT)
```

Binding `0.0.0.0:8765` on Windows does not necessarily fail when something already holds `127.0.0.1:8765`, and the more specific listener wins for loopback traffic — so the server can appear to start while every browser request reaches the other application. Check explicitly rather than relying on the bind to fail.

- [ ] **Step 1: Write the failing tests**

```python
def test_port_is_free_reports_false_when_something_is_listening():
    import socket
    from transcoder.api.__main__ import port_is_free
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert port_is_free("127.0.0.1", port) is False
    finally:
        s.close()


def test_port_is_free_reports_true_for_an_unused_port():
    import socket
    from transcoder.api.__main__ import port_is_free
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                      # now free
    assert port_is_free("127.0.0.1", port) is True


def test_main_exits_with_a_clear_message_when_the_port_is_taken(monkeypatch, capsys):
    """Must NOT start uvicorn: a server nobody can reach is worse than a
    refusal, because the browser then shows whatever else owns the port."""
    import transcoder.api.__main__ as m
    started = []
    monkeypatch.setattr(m.uvicorn, "run", lambda *a, **k: started.append(True))
    monkeypatch.setattr(m, "port_is_free", lambda host, port: False)
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code != 0
    assert not started
    out = capsys.readouterr()
    assert str(m.settings.API_PORT) in (out.out + out.err)
```

- [ ] **Step 2: Run and watch them fail** (`ImportError` on `port_is_free`).

- [ ] **Step 3: Implement**

Add `port_is_free(host, port)` using a short-timeout `socket.connect_ex` against the loopback address (checking whether anything ANSWERS is the right question here, not whether we can bind). In `main()`, call it before `uvicorn.run`; on failure print a message naming the port and telling the user to free it or set `API_PORT`, then `raise SystemExit(1)`.

If you can identify the occupying process cheaply and portably, include it — but **do not** add a dependency or shell out to `netstat` parsing for it. A clear port message is the requirement; naming the process is a bonus.

- [ ] **Step 4: Verify** — `python -m pytest -q`, green, count up by 3.

- [ ] **Step 5: Report (do not commit)**

---

### Task 3: Make the tray tell the truth

**Files:**
- Modify: `solution/tray.pyw`

**Interfaces:** none. No tests — this file is a GUI entry point with no existing test coverage; verification is by reading and by the manual check in Step 4.

Three defects, all visible in the incident:

1. `BASE_URL = "http://localhost:8765"` (line ~60) and `_find_server_pid()` (line ~207, matching `":8765 "`) hardcode the port, so configuring `API_PORT` breaks the tray.
2. `_open_ui` (line ~222) calls `webbrowser.open(BASE_URL)` unconditionally — including when the server never started, which is how an install crash presented as "the UI opens something else".
3. A server that dies during startup produces no notification at all; the evidence sat unread in `log/server_start.log`.

- [ ] **Step 1: Read the file first**

Read `solution/tray.pyw` fully. It already has `_is_up()` (health poll), `_notify()` (toast) and a logger. Reuse them rather than adding new machinery.

- [ ] **Step 2: Derive the port from config**

Replace the hardcoded `8765` in both `BASE_URL` and `_find_server_pid` with the configured value. The tray runs with cwd = `solution/`, so `from transcoder.config import settings` should work — verify it does not pull in the database at import (Task 1 is about exactly that class of problem). If importing config from the tray is not safe or not available, read `API_PORT` from the environment/`.env` with a `8765` default, and say in your report which route you took and why.

- [ ] **Step 3: Only open the UI once the server answers**

After `_start_server`, poll `_is_up()` for a bounded period (about 20 s, then give up). If it comes up, proceed as now. If it does not, `_notify(...)` that the server failed to start and name `log/server_start.log` as the place to look. Make `_open_ui` refuse to open a browser when `_is_up()` is false, notifying instead — an unreachable port shows the user someone else's application.

- [ ] **Step 4: Verify manually**

There are no tests here. Confirm `python -c "import ast; ast.parse(open('solution/tray.pyw').read())"` parses, run the full backend suite to prove nothing else broke, and state clearly in your report that the tray behaviour itself is unverified by automated tests.

- [ ] **Step 5: Report (do not commit)**

---

## Self-Review

**1. Coverage.** Task 1 fixes the crash; Task 2 makes a taken port a refusal rather than a silent misdirection; Task 3 stops the tray reporting success it has not checked. The incident had all three.

**2. Placeholders.** None. Task 2 Step 3 leaves the process-identification detail open, deliberately bounded ("a clear port message is the requirement").

**3. Type consistency.** `port_is_free(host, port) -> bool` is named identically in Task 2's tests and implementation. `WorkerController.clients` is introduced in Task 1 Step 3 and used nowhere else.

**4. Risk.** Task 1's property makes `self._clients` change type after first access. That is contained within the class, but a worker must replace *every* internal read, not just the obvious one — Step 4's full-suite run is the guard.

**5. Ordering.** Task 1 first: without it there is nothing to connect to and Tasks 2 and 3 cannot be exercised end to end. Tasks 2 and 3 touch disjoint files and may run together afterwards.
