import os

from transcoder.arr_import import ImportNotQueued
from transcoder.engine.worker import process_one_job
from transcoder.models import Job, MediaItem


class RejectingClient:
    def manual_import_one(self, path):
        raise ImportNotQueued("Radarr rejected /downloads/M.mkv: Not an upgrade for existing movie file(s)")


def test_rejected_import_fails_job_and_keeps_item_eligible(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = MediaItem(source="radarr", external_id="2749", title="M", year=2025,
                     remote_path="/movies/M.mkv", resolution=1080,
                     quality="Bluray-1080p Proper", languages="ENG",
                     eligibility="needs_transcode")
    session.add(item)
    session.commit()
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    def download(host, port, user, pw, remote, local, progress_cb=None):
        return {"success": True}

    def upload(host, port, user, pw, local, remote, progress_cb=None):
        return {"success": True}

    def convert(tmp, out_name, preset, progress_cb=None, cancel_event=None, handbrake_cli=None):
        return ("./out/" + out_name, False)

    process_one_job(session, job, {"radarr": RejectingClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "failed"
    assert "Not an upgrade" in job.error_message
    assert job.output_filename is None
    assert item.eligibility == "needs_transcode"   # not falsely marked already_h265
    assert "Bluray-1080p Proper Release-" in job.log  # Proper reached the uploaded filename
