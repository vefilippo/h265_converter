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
