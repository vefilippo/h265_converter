import logging
import os

from transcoder.log_buffer import RingBufferHandler
from transcoder.engine.worker import process_one_job
from transcoder.models import Job, MediaItem


def test_worker_logs_transitions(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    buf = RingBufferHandler()
    logger = logging.getLogger("transcoder")
    logger.addHandler(buf)
    logger.setLevel(logging.INFO)
    try:
        item = MediaItem(source="sonarr", external_id="1", title="Show A", season=1,
                         episode=1, remote_path="/TVShows/a.mkv", resolution=1080,
                         quality="HDTV-1080p", languages="ENG", eligibility="needs_transcode")
        session.add(item); session.commit()
        job = Job(media_item_id=item.id, state="queued"); session.add(job); session.commit()

        class FakeClient:
            def manual_import_one(self, p): pass

        def convert(tmp, out, preset, progress_cb=None, cancel_event=None):
            return ("./out/" + out, False)

        process_one_job(session, job, {"sonarr": FakeClient()},
                        download=lambda *a, **k: None, upload=lambda *a, **k: None, convert=convert)
        msgs = " ".join(l["message"] for l in buf.after(0))
        assert "Job" in msgs
        assert "done" in msgs.lower()
    finally:
        logger.removeHandler(buf)
