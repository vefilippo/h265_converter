#!/usr/bin/env python3
import argparse
import logging

from transcoder.logging_setup import init_logging
from transcoder.config import settings
from transcoder.db import SessionLocal, init_db
from transcoder.migrate import migrate_legacy
from transcoder.sonarr_client import SonarrClient
from transcoder.radarr_client import RadarrClient
from transcoder.engine.discovery import discover_sonarr, discover_radarr
from transcoder.engine.queue import enqueue_eligible
from transcoder.engine.worker import process_queue
from transcoder.models import Job

log = logging.getLogger("transcoder")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcode Sonarr/Radarr media to H.265")
    parser.add_argument("command", choices=["scan", "run", "queue"],
                        help="scan: discover only; run: discover+enqueue+process; queue: list jobs")
    parser.add_argument("app", nargs="?", choices=["all", "sonarr", "radarr"], default="all")
    parser.add_argument("scope", nargs="?", choices=["all", "new"], default="all")
    parser.add_argument("--show", help="Sonarr: only this exact series title")
    parser.add_argument("--movie", help="Radarr: only this exact movie title")
    return parser


def _discover(session, clients, app, scope, show, movie):
    if app in ("all", "sonarr"):
        n = discover_sonarr(session, clients["sonarr"], scope=scope, target_title=show)
        log.info("Sonarr discovery: %s items", n)
    if app in ("all", "radarr"):
        n = discover_radarr(session, clients["radarr"], target_movie=movie)
        log.info("Radarr discovery: %s items", n)


def main() -> None:
    init_logging("cli")
    init_db()
    args = build_parser().parse_args()

    with SessionLocal() as session:
        # MUST run before anything reads/writes preset settings, mirroring
        # api/app.py's startup ordering: backfills encoder_family so a
        # pre-existing install's hand-tuned handbrake_preset_1080/_4k is
        # inferred as its matching family instead of resolve_for_job silently
        # defaulting an un-migrated install to 'auto'.
        from transcoder.encoders import migrate_encoder_family
        if migrate_encoder_family(session) is not None:
            session.commit()

        migrate_legacy(session)

        if args.command == "queue":
            for job in session.query(Job).order_by(Job.id).all():
                log.info("Job %s | %s | progress=%s%% | item=%s",
                         job.id, job.state, job.progress, job.media_item.title)
            return

        # Built once here (not needed for the queue listing above) and shared by
        # both discovery and the worker.
        clients = {
            "sonarr": SonarrClient(settings.SONARR_URL, settings.SONARR_API_KEY),
            "radarr": RadarrClient(settings.RADARR_URL, settings.RADARR_API_KEY),
        }

        _discover(session, clients, args.app, args.scope, args.show, args.movie)

        if args.command == "run":
            created = enqueue_eligible(session,
                                      source=None if args.app == "all" else args.app)
            log.info("Enqueued %s jobs", created)
            processed = process_queue(session, clients)
            log.info("Processed %s jobs", processed)


if __name__ == "__main__":
    main()
