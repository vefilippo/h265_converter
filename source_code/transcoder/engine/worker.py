import os
import re

from transcoder.config import settings
from transcoder.convert import convert_with_handbrake
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


def _exclusion_key(item) -> str:
    if item.source == "sonarr":
        return episode_exclusion_key(item.title, item.season, item.episode)
    return movie_exclusion_key(item.title)


def process_one_job(
    session,
    job,
    clients,
    *,
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
        job.started_at = utcnow()
        job.progress = 0
        job.preset = settings.PRESET_4K if item.resolution > 1080 else settings.PRESET_1080
        session.commit()

        os.makedirs("./tmp", exist_ok=True)
        file_path = _local_path(item)
        tmp_file = os.path.join("./tmp", os.path.basename(file_path))
        download(settings.SFTP_HOST, settings.SFTP_PORT, settings.SFTP_USERNAME,
                 settings.SFTP_PASSWORD, file_path, tmp_file)

        original_size = os.path.getsize(tmp_file)
        out_name = _output_name(item)

        def cb(pct):
            job.progress = pct
            session.commit()

        output_file, exclude_flag = convert(tmp_file, out_name, job.preset, progress_cb=cb)

        if output_file is None:
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
            session.add(Exclusion(source=item.source, key=_exclusion_key(item),
                                  reason="output_larger"))
            item.eligibility = "excluded"
            job.state = "skipped_larger"
        else:
            upload(settings.SFTP_HOST, settings.SFTP_PORT, settings.SFTP_USERNAME,
                   settings.SFTP_PASSWORD, output_file, settings.WATCH_FOLDER + out_name)
            client.manual_import_one(output_file)
            item.eligibility = "already_h265"
            job.output_filename = out_name
            job.state = "done"

        job.finished_at = utcnow()
        session.commit()
        return job

    except Exception as exc:  # noqa: BLE001 — record failure, keep draining queue
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
