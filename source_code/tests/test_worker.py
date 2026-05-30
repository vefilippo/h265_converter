import os

from transcoder.engine.worker import process_one_job, process_queue, reconcile_stale_jobs
from transcoder.models import Exclusion, Job, MediaItem


def test_reconcile_stale_jobs_requeues_only_running(session):
    item = MediaItem(source="sonarr", external_id="1", title="A", season=1,
                     episode=1, remote_path="/x", resolution=1080,
                     eligibility="needs_transcode")
    session.add(item)
    session.commit()
    session.add(Job(media_item_id=item.id, state="running", progress=42))
    session.add(Job(media_item_id=item.id, state="queued"))
    session.add(Job(media_item_id=item.id, state="done"))
    session.commit()

    n = reconcile_stale_jobs(session)
    assert n == 1
    # The stale 'running' became 'queued'; the others are untouched.
    assert sorted(j.state for j in session.query(Job).all()) == ["done", "queued", "queued"]
    # The reset job's progress was cleared.
    assert session.query(Job).filter_by(progress=42).all() == []


class FakeClient:
    def __init__(self):
        self.imported = []

    def manual_import_one(self, path):
        self.imported.append(path)


def _item(session, **kw):
    defaults = dict(
        source="sonarr", external_id="1", title="Show A", season=1, episode=1,
        remote_path="/TVShows/a.mkv", resolution=1080, quality="HDTV-1080p",
        languages="ENG", eligibility="needs_transcode",
    )
    defaults.update(kw)
    item = MediaItem(**defaults)
    session.add(item)
    session.commit()
    return item


def _make_io(smaller=True, fail=False):
    calls = {"download": [], "upload": [], "removed": []}

    def download(host, port, user, pw, remote, local):
        calls["download"].append((remote, local))
        return {"success": True}

    def upload(host, port, user, pw, local, remote):
        calls["upload"].append((local, remote))
        return {"success": True}

    def convert(tmp, out_name, preset, progress_cb=None, cancel_event=None):
        if progress_cb:
            progress_cb(50)
            progress_cb(100)
        if fail:
            return None, False
        return ("./out/" + out_name, not smaller)

    return calls, download, upload, convert


def test_worker_success_smaller(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(smaller=True)
    client = FakeClient()
    process_one_job(session, job, {"sonarr": client},
                    download=download, upload=upload, convert=convert)

    assert job.state == "done"
    assert job.progress == 100
    assert len(calls["upload"]) == 1
    assert len(client.imported) == 1
    assert job.preset == "H.265 NVENC 1080p"


def test_worker_larger_excludes(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(smaller=False)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "skipped_larger"
    assert session.query(Exclusion).filter_by(source="sonarr", key="Show A|1|1").count() == 1
    assert item.eligibility == "excluded"
    assert len(calls["upload"]) == 0


def test_worker_convert_failure(session, monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(fail=True)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "failed"
    assert job.error_message


def test_worker_cleans_up_tmp_on_convert_failure(session, monkeypatch):
    removed = []
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: removed.append(p))
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = _item(session)
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    calls, download, upload, convert = _make_io(fail=True)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "failed"
    # the downloaded temp file must be reclaimed even though convert failed
    assert any(os.path.basename(p) == "a.mkv" for p in removed)


def test_process_queue_drains(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    for i in range(3):
        item = _item(session, external_id=str(i))
        session.add(Job(media_item_id=item.id, state="queued"))
    session.commit()

    calls, download, upload, convert = _make_io(smaller=True)
    processed = process_queue(session, {"sonarr": FakeClient()},
                              download=download, upload=upload, convert=convert)
    assert processed == 3
    assert session.query(Job).filter_by(state="done").count() == 3
