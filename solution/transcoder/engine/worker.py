import datetime as _dt
import logging
import os
import re

from transcoder.config import settings
from transcoder.encoders import AUTO, CPU, FAMILIES, resolve_for_job
from transcoder.repo import get_effective

log = logging.getLogger("transcoder")
from transcoder.convert import convert_with_handbrake, TranscodeCancelled
from transcoder.models import Exclusion, Job, episode_exclusion_key, movie_exclusion_key, utcnow
from transcoder.sftp_client import download_file_via_sftp, upload_file_via_sftp


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9 \-]", "", name)


def _local_path(item) -> str:
    if item.source == "sonarr":
        return item.remote_path.replace("/TVShows/", settings.LOCAL_FOLDER)
    return item.remote_path.replace("/movies/", settings.LOCAL_FOLDER_MOVIES).replace("/", "\\")


def _output_name(item) -> str:
    title = _sanitize(item.title)
    if item.source == "sonarr":
        return (
            f"{title} - S{item.season:02}E{item.episode:02} - h265 - "
            f"[{item.languages}] {item.quality} {settings.RELEASE_TAG}.mkv"
        )
    return f"{title} ({item.year}) [h265] [{item.languages}] {item.quality} {settings.RELEASE_TAG}.mkv"


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


def _exclusion_key(item) -> str:
    if item.source == "sonarr":
        return episode_exclusion_key(item.title, item.season, item.episode)
    return movie_exclusion_key(item.title)


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
    item = job.media_item
    client = clients[item.source]
    tmp_file = None
    output_file = None

    try:
        # Transition to running inside the try so a commit failure here is
        # recorded as 'failed' (otherwise the job stays 'queued' and
        # process_queue would re-pick it forever).
        job.state = "running"
        job.phase = "downloading"
        job.started_at = utcnow()
        job.progress = 0
        resolution = resolve_for_job(session)
        job.preset = (
            resolution.preset_4k if item.resolution > 1080 else resolution.preset_1080
        )
        session.commit()
        job_log(session, job, f"Downloading {item.title}")

        os.makedirs("./tmp", exist_ok=True)
        file_path = _local_path(item)
        ext = os.path.splitext(os.path.basename(file_path))[1]
        tmp_file = os.path.join("./tmp", f"job_{job.id}{ext}")
        dl = download(
            get_effective(session, "sftp_host", settings.SFTP_HOST),
            int(get_effective(session, "sftp_port", str(settings.SFTP_PORT))),
            get_effective(session, "sftp_username", settings.SFTP_USERNAME),
            get_effective(session, "sftp_password", settings.SFTP_PASSWORD),
            file_path, tmp_file,
            progress_cb=_progress_writer(session, job),
        )
        if isinstance(dl, dict) and dl.get("success") is False:
            raise RuntimeError(f"download failed: {dl.get('message')}")

        original_size = os.path.getsize(tmp_file)
        out_name = _output_name(item)

        job.phase = "transcoding"
        job.progress = 0
        session.commit()
        job_log(session, job, f"Transcoding {item.title} (preset {job.preset})")
        if resolution.substituted:
            requested = FAMILIES[resolution.requested]["label"]
            job_log(
                session, job,
                f"{requested} is not available on this host; falling back to "
                "CPU x265 — this will be substantially slower",
            )
        elif resolution.detection_unknown:
            if resolution.family == CPU and resolution.requested == AUTO:
                # 'auto' with unknown capabilities silently lands on CPU x265
                # (see resolve()) -- that's the one detection_unknown case
                # that is itself a slow substitution, so it gets the same loud
                # wording as an explicit substituted fallback.
                job_log(
                    session, job,
                    "Encoder detection unavailable; no hardware encoder could "
                    "be confirmed, using CPU x265 — substantially slower",
                )
            else:
                job_log(
                    session, job,
                    "Encoder detection unavailable; running the configured preset as set",
                )
        output_file, exclude_flag = convert(
            tmp_file, out_name, job.preset,
            progress_cb=_progress_writer(session, job),
            cancel_event=cancel_event,
            handbrake_cli=get_effective(session, "handbrake_cli", settings.HANDBRAKE_CLI),
        )

        if output_file is None:
            job_log(session, job, "HandBrake failed")
            job.phase = None
            job.state = "failed"
            job.error_message = "HandBrake conversion failed"
            job.finished_at = utcnow()
            session.commit()
            return job

        job.original_size = original_size
        job.output_size = os.path.getsize(output_file)
        if job.original_size:
            job.reduction_pct = (job.original_size - job.output_size) / job.original_size * 100

        if exclude_flag:
            job_log(session, job, "Skipped (output larger)")
            job.phase = None
            session.add(Exclusion(source=item.source, key=_exclusion_key(item),
                                  reason="output_larger"))
            item.eligibility = "excluded"
            job.state = "skipped_larger"
        else:
            job.phase = "uploading"
            job.progress = 0
            session.commit()
            job_log(session, job, f"Uploading {out_name}")
            up = upload(
                get_effective(session, "sftp_host", settings.SFTP_HOST),
                int(get_effective(session, "sftp_port", str(settings.SFTP_PORT))),
                get_effective(session, "sftp_username", settings.SFTP_USERNAME),
                get_effective(session, "sftp_password", settings.SFTP_PASSWORD),
                output_file, settings.WATCH_FOLDER + out_name,
                progress_cb=_progress_writer(session, job),
            )
            if isinstance(up, dict) and up.get("success") is False:
                raise RuntimeError(f"upload failed: {up.get('message')}")
            client.manual_import_one(output_file)
            item.eligibility = "already_h265"
            job.output_filename = out_name
            job.state = "done"
            job_log(session, job, f"Done {item.title} ({job.reduction_pct or 0.0:.1f}% smaller)")

        job.phase = None
        job.finished_at = utcnow()
        session.commit()
        return job

    except TranscodeCancelled:
        job.phase = None
        job_log(session, job, "Cancelled")
        job.state = "cancelled"
        job.error_message = "cancelled by user"
        job.finished_at = utcnow()
        session.commit()
        return job

    except Exception as exc:  # noqa: BLE001 — record failure, keep draining queue
        job.phase = None
        job_log(session, job, f"Failed: {exc}")
        job.state = "failed"
        job.error_message = str(exc)
        job.finished_at = utcnow()
        session.commit()
        return job

    finally:
        # Always reclaim local disk: the temp download and the transcoded
        # output (uploaded already on success; orphaned on skip/failure).
        for path in (tmp_file, output_file):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def reconcile_stale_jobs(session) -> int:
    """Re-queue jobs orphaned in 'running' by a previous crash/restart.

    The worker is serial and nothing is in flight at startup, so any 'running'
    row is stale — the process died mid-transcode. Reset it to 'queued' (clear
    progress/started_at) so the worker picks it up again instead of leaving it
    stuck. Returns the number reset."""
    rows = session.query(Job).filter(Job.state == "running").all()
    for job in rows:
        job.state = "queued"
        job.progress = 0
        job.started_at = None
    if rows:
        session.commit()
        log.info("Reconciled %d stale running job(s) to queued", len(rows))
    return len(rows)


def process_queue(session, clients, *, limit: int | None = None, **io) -> int:
    processed = 0
    while True:
        job = (
            session.query(Job)
            .filter(Job.state == "queued")
            .order_by(Job.id)
            .first()
        )
        if job is None:
            break
        process_one_job(session, job, clients, **io)
        processed += 1
        if limit and processed >= limit:
            break
    return processed
