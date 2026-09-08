"""Retire media_item rows whose Sonarr episodeFile no longer exists.

Sonarr mints a new episodeFileId every time the file behind an episode changes
-- a quality upgrade it grabbed itself, or our own transcode being re-imported.
media_item is keyed on (source, external_id) == episodeFileId, so the row for
the old id is orphaned: discovery walks Sonarr's *current* episodes, never
visits that id again, and so never refreshes or removes it. Those orphans
duplicate the Library, and one left at 'needs_transcode' is re-enqueued on
every run and fails on download forever.

Orphans are marked 'superseded' rather than deleted: job rows reference them
and deleting would orphan that history.
"""

import logging

from sqlalchemy import func

from transcoder.models import MediaItem

log = logging.getLogger("transcoder")

SUPERSEDED = "superseded"

_BATCH = 200  # commit cadence, matching discovery's


def _series_with_duplicates(session) -> list[int]:
    """Series ids holding more than one live row for the same (season, episode).

    Already-superseded rows are excluded, so a series drops out of the
    candidate set once it has been reaped instead of being re-queried on every
    run.
    """
    rows = (
        session.query(MediaItem.parent_id)
        .filter(
            MediaItem.source == "sonarr",
            MediaItem.eligibility != SUPERSEDED,
        )
        .group_by(MediaItem.parent_id, MediaItem.season, MediaItem.episode)
        .having(func.count(MediaItem.id) > 1)
        .all()
    )
    return sorted({pid for (pid,) in rows if pid is not None})


def reap_orphans(session, client, *, batch_size: int = _BATCH) -> int:
    """Retire orphaned Sonarr media_item rows; return how many were retired.

    Only series that show a duplicated episode are queried -- 46 of 201 on the
    production library. For each, Sonarr's live episodeFileId set is
    authoritative for the WHOLE series, so a dead row in an episode that is not
    itself duplicated is retired in the same pass.
    """
    series_ids = _series_with_duplicates(session)
    if not series_ids:
        return 0

    log.info("Reap: checking %d series with duplicated episodes", len(series_ids))
    retired = 0
    for series_id in series_ids:
        live = {
            str(ep["episodeFileId"])
            for ep in client.get_episodes(series_id)
            if ep.get("hasFile") and ep.get("episodeFileId")
        }
        rows = (
            session.query(MediaItem)
            .filter(
                MediaItem.source == "sonarr",
                MediaItem.parent_id == series_id,
                MediaItem.eligibility != SUPERSEDED,
            )
            .all()
        )
        for item in rows:
            if item.external_id not in live:
                item.eligibility = SUPERSEDED
                retired += 1
                if retired % batch_size == 0:
                    session.commit()

    session.commit()
    log.info("Reap: retired %d orphaned media item(s)", retired)
    return retired
