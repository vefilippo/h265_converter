"""Exercise the actual HTTP restore, process exit, relaunch and SQLite bootstrap."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import httpx
from sqlalchemy.orm import Session

from transcoder.db import Base, make_engine
from transcoder.models import Exclusion, Job, MediaItem


def test_http_restore_recovers_library_jobs_and_exclusions_after_restart(tmp_path):
    database = tmp_path / "transcoder.db"
    engine = make_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        item = MediaItem(source="radarr", external_id="42", title="Saved movie",
                         eligibility="excluded", codec="h264", resolution=1080)
        session.add(item)
        session.flush()
        session.add(Job(media_item_id=item.id, state="done", progress=100,
                        original_size=1000, output_size=600, log="Saved job log"))
        session.add(Exclusion(source="radarr", key="Saved movie", reason="manual"))
        session.commit()
    engine.dispose()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update(DATABASE_URL=f"sqlite:///{database.as_posix()}", API_HOST="127.0.0.1",
               API_PORT=str(port), APP_PASSWORD="restore-test", SECRET_KEY="restore-test",
               SONARR_URL="", RADARR_URL="", SFTP_HOST="",
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / "solution"))
    # Only add PID recording to the real waiter so cleanup owns the relaunched
    # process as well. The production wait, launch, API and bootstrap stay real.
    child_pid_file = tmp_path / "child.pid"
    harness = (
        "from transcoder import restore\n"
        "original=restore._waiter_script\n"
        "def tracked(*a,**k):\n"
        "    source=original(*a,**k).replace('subprocess.Popen(', 'child=subprocess.Popen(')\n"
        f"    return source + {('from pathlib import Path; Path(' + repr(str(child_pid_file)) + ').write_text(str(child.pid))' + chr(10))!r}\n"
        "restore._waiter_script=tracked\n"
        "from transcoder.api.__main__ import main\n"
        "main()\n"
    )
    log_file = (tmp_path / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-c", harness], cwd=tmp_path,
                               env=env, stdout=log_file, stderr=log_file)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2)

    def wait_for_health():
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if client.get("/api/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise AssertionError((tmp_path / "server.log").read_text(encoding="utf-8"))

    try:
        wait_for_health()
        assert client.post("/api/login", json={"password": "restore-test"}).status_code == 200
        response = client.post("/api/backup", json={"passphrase": "pw"})
        assert response.status_code == 200
        blob = response.content
        with Session(engine) as session:
            session.query(Job).delete()
            session.query(Exclusion).delete()
            session.query(MediaItem).delete()
            session.commit()
        engine.dispose()
        assert client.get("/api/jobs").json()["total"] == 0
        response = client.post("/api/restore", files={"file": ("backup.zip", blob)},
                               data={"passphrase": "pw"}, timeout=20)
        assert response.status_code == 202
        process.wait(timeout=20)  # The original bug never stops this process.
        wait_for_health()
        assert client.post("/api/login", json={"password": "restore-test"}).status_code == 200
        jobs = client.get("/api/jobs").json()
        assert jobs["total"] == 1
        assert jobs["items"][0]["state"] == "done"
        # Read persisted fields, including those omitted from list responses.
        with Session(engine) as session:
            job = session.query(Job).one()
            assert (job.progress, job.original_size, job.output_size, job.log) == (
                100, 1000, 600, "Saved job log")
            item = session.query(MediaItem).one()
            assert (item.title, item.eligibility) == ("Saved movie", "excluded")
            exclusion = session.query(Exclusion).one()
            assert (exclusion.key, exclusion.reason) == ("Saved movie", "manual")
    finally:
        client.close()
        engine.dispose()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        # Waiter may still be launching the replacement after an assertion fails.
        deadline = time.monotonic() + 3
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if child_pid_file.exists():
            try:
                os.kill(int(child_pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
        log_file.close()
