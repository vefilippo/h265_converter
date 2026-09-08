"""Backstop for orphans the duplicate-driven reap cannot see.

`reap_orphans` finds orphans by spotting two rows for the same episode. An
episode whose file is deleted with no replacement leaves a LONE stale row, so
it is invisible to that pass — and if it sits at `needs_transcode` it is
re-enqueued on every run and fails on download, forever (21 consecutive failed
jobs on the real install before this was found).

So the worker retires the item itself the moment SFTP reports the source file
is gone. Transient failures must NOT retire anything.
"""

from transcoder.engine.queue import enqueue_eligible
from transcoder.engine.worker import process_one_job
from transcoder.models import Job, MediaItem


class FakeClient:
    def manual_import_one(self, path):  # pragma: no cover - never reached here
        raise AssertionError("import must not run when the download failed")


def _queued_job(session):
    item = MediaItem(
        source="sonarr", external_id="35817", parent_id=199, title="The Ark",
        season=3, episode=5, remote_path="/TVShows/The Ark/S03E05.mkv",
        resolution=1080, quality="WEBDL-1080p", languages="ENGLISH",
        eligibility="needs_transcode",
    )
    session.add(item)
    session.commit()
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()
    return item, job


def _run(session, job, message):
    def download(host, port, user, pw, remote, local, progress_cb=None):
        return {"success": False, "message": message}

    def unused(*args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("must not run after a failed download")

    return process_one_job(
        session, job, {"sonarr": FakeClient()},
        download=download, upload=unused, convert=unused,
    )


def test_missing_source_file_retires_the_library_item(session):
    item, job = _queued_job(session)

    _run(session, job, "[Errno 2] No such file")

    assert job.state == "failed"
    assert item.eligibility == "superseded"


def test_retired_item_is_not_enqueued_again(session):
    item, job = _queued_job(session)

    _run(session, job, "[Errno 2] No such file")

    assert enqueue_eligible(session) == 0


def test_transient_download_failure_leaves_the_item_eligible(session):
    # A dropped connection or a bad password says nothing about the file; the
    # item must stay queueable so the next run retries it.
    item, job = _queued_job(session)

    _run(session, job, "Authentication failed.")

    assert job.state == "failed"
    assert item.eligibility == "needs_transcode"
    assert enqueue_eligible(session) == 1
