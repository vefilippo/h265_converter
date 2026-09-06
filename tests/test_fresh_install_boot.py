"""A fresh install boots against a database that has no tables yet.

Regression guard for the 2026-09-06 field defect: the installed app died at
import with `sqlite3.OperationalError: no such table: setting`, before uvicorn
ever bound, because `transcoder/api/state.py` built its singletons at module
scope and `build_clients()` reads the `setting` table -- which the lifespan's
`init_db()` had not yet created.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOLUTION = REPO_ROOT / "solution"


def test_app_imports_and_builds_against_an_empty_database(tmp_path):
    """A fresh install has a database file with NO tables. Importing the API
    must not query one."""
    db = tmp_path / "transcoder.db"
    db.touch()                      # exists, but contains no tables
    script = textwrap.dedent("""
        from transcoder.api.app import create_app
        create_app(start_worker=False)
        print("OK")
    """)
    full_env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db.as_posix()}",
        "PYTHONPATH": str(SOLUTION),
    }
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path, env=full_env,
        capture_output=True, text=True, timeout=120,
    )
    combined = proc.stdout + proc.stderr
    assert "no such table" not in combined, combined
    assert proc.returncode == 0, combined
    assert "OK" in proc.stdout


def test_worker_controller_resolves_a_clients_factory_on_first_use():
    """state.py hands the controller `build_clients` itself rather than calling
    it, so nothing opens the database at import. The worker must therefore
    resolve the factory before handing clients to the job processor -- passing
    the raw function through would break every job."""
    from transcoder.models import Job
    from transcoder.worker_controller import WorkerController

    real_clients = {"sonarr": object(), "radarr": object()}
    calls = []

    def factory():
        calls.append(1)
        return real_clients

    seen = []

    def fake_process(session, job, clients, cancel_event=None):
        seen.append(clients)
        job.state = "done"

    class FakeSession:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def first(self):
            return None

        def close(self):
            pass

    ctl = WorkerController(FakeSession, factory, process=fake_process)
    assert calls == [], "the factory must not be called before it is needed"

    job = Job(id=1, media_item_id=1, state="queued")
    ctl._process(FakeSession(), job, ctl.clients, cancel_event=None)

    assert seen == [real_clients]
    assert ctl.clients is real_clients
    assert calls == [1], "the factory must be resolved exactly once"


def test_worker_controller_still_accepts_a_plain_clients_dict():
    """The dict form is used throughout the suite and must keep working."""
    from transcoder.worker_controller import WorkerController

    clients = {"sonarr": object(), "radarr": object()}
    ctl = WorkerController(lambda: None, clients)
    assert ctl.clients is clients
