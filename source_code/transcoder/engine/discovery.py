import datetime as dt
import logging

from transcoder import repo
from transcoder.engine.eligibility import compute_eligibility
from transcoder.history import _parse_iso_z
from transcoder.models import episode_exclusion_key, movie_exclusion_key

log = logging.getLogger("transcoder")


def _watermark_iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


_BATCH = 200  # commit cadence so a long scan doesn't hold the write lock


def discover_sonarr(session, client, scope: str = "all", target_title=None,
                    batch_size: int = _BATCH) -> int:
    """Scan Sonarr and upsert MediaItem rows; return the count of items scanned.

    scope="new" only processes series with recent history (via the stored
    watermark) and advances the watermark afterwards. target_title restricts to
    one series. Note: when target_title is set it takes precedence over the
    recent-ids filter, but the watermark is still advanced (parity with the
    original script).

    Commits every ``batch_size`` items so the SQLite write lock is released
    frequently — letting the worker and API writers interleave instead of
    hitting "database is locked" during a multi-thousand-item scan.
    """
    excluded = repo.excluded_keys(session, "sonarr")
    watermark = None
    recent_ids = set()
    newest = None

    if scope == "new":
        raw = repo.get_setting(session, "sonarr_watermark")
        watermark = _parse_iso_z(raw) if raw else None
        recent_ids, newest = client.get_recent_series_ids(watermark)

    series_list = client.get_all_series()
    if target_title:
        series_list = [s for s in series_list if s["title"].lower() == target_title.lower()]
    elif scope == "new" and watermark is not None:
        series_list = [s for s in series_list if s["id"] in recent_ids]

    log.info("Sonarr scan: checking %d series (scope=%s)", len(series_list), scope)
    count = 0
    for series in series_list:
        log.info("Checking series: %s", series["title"])
        for ep in client.get_episodes(series["id"]):
            if not ep.get("hasFile"):
                continue
            ef = client.get_episode_file(ep["episodeFileId"])
            if not ef:
                continue
            resolution = client.extract_resolution(ef)
            is_h265 = client.is_h265_encoded(ef)
            key = episode_exclusion_key(series["title"], ep["seasonNumber"], ep["episodeNumber"])
            repo.upsert_media_item(
                session,
                source="sonarr",
                external_id=str(ep["episodeFileId"]),
                parent_id=series["id"],
                title=series["title"],
                season=ep["seasonNumber"],
                episode=ep["episodeNumber"],
                remote_path=ef.get("path", ""),
                resolution=resolution,
                quality=client.extract_quality(ef),
                languages=client.extract_languages(ef),
                size_bytes=ef.get("size"),
                is_h265=is_h265,
                codec=None,
                eligibility=compute_eligibility(resolution, is_h265, key in excluded),
            )
            count += 1
            if count % batch_size == 0:
                session.commit()

    if scope == "new" and newest is not None:
        repo.set_setting(session, "sonarr_watermark", _watermark_iso(newest))

    session.commit()
    log.info("Sonarr scan complete: %d episode file(s) processed", count)
    return count


def discover_radarr(session, client, target_movie=None, batch_size: int = _BATCH) -> int:
    """Scan Radarr (always all movies) and upsert non-H.265 MediaItem rows;
    return the count of items scanned. target_movie restricts to one movie.

    Commits every ``batch_size`` items (see discover_sonarr) to keep the write
    lock short and avoid blocking the worker / API writers."""
    excluded = repo.excluded_keys(session, "radarr")
    rows = client.filter_non_h265_movies(client.get_all_movies())
    if target_movie:
        rows = [r for r in rows if r["title"].lower() == target_movie.lower()]

    log.info("Radarr scan: checking %d non-H.265 movie(s)", len(rows))
    count = 0
    for r in rows:
        log.info("Checking movie: %s", r["title"])
        key = movie_exclusion_key(r["title"])
        resolution = r["resolution"] or 0
        repo.upsert_media_item(
            session,
            source="radarr",
            external_id=r["external_id"],
            parent_id=r["movie_id"],
            title=r["title"],
            year=r["year"],
            remote_path=r["path"],
            resolution=resolution,
            quality=r["quality"],
            languages=r["languages"],
            codec=r["codec"],
            is_h265=False,
            eligibility=compute_eligibility(resolution, False, key in excluded),
        )
        count += 1
        if count % batch_size == 0:
            session.commit()

    session.commit()
    log.info("Radarr scan complete: %d movie(s) processed", count)
    return count
