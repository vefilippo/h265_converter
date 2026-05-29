import csv
import os

from transcoder.config import settings
from transcoder.models import Exclusion, Setting, episode_exclusion_key, movie_exclusion_key


def _add_exclusion(session, source: str, key: str) -> bool:
    exists = (
        session.query(Exclusion).filter_by(source=source, key=key).first() is not None
    )
    if exists:
        return False
    session.add(Exclusion(source=source, key=key, reason="output_larger"))
    return True


def migrate_legacy(session) -> dict:
    result = {"episodes": 0, "movies": 0, "watermark": False}
    to_rename = []

    ep_csv = settings.EPISODE_EXCLUSION_CSV
    if os.path.exists(ep_csv):
        with open(ep_csv, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 3:
                    continue
                if _add_exclusion(session, "sonarr",
                                  episode_exclusion_key(row[0], row[1], row[2])):
                    result["episodes"] += 1
        to_rename.append(ep_csv)

    mv_csv = settings.MOVIE_EXCLUSION_CSV
    if os.path.exists(mv_csv):
        with open(mv_csv, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row:
                    continue
                if _add_exclusion(session, "radarr", movie_exclusion_key(row[0])):
                    result["movies"] += 1
        to_rename.append(mv_csv)

    hist = settings.LAST_HISTORY_FILE
    if os.path.exists(hist):
        with open(hist, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw and session.get(Setting, "sonarr_watermark") is None:
            session.add(Setting(key="sonarr_watermark", value=raw))
            result["watermark"] = True
        to_rename.append(hist)

    # Persist all rows BEFORE touching the filesystem, so a crash can't leave
    # legacy data neither on disk nor in the DB. os.replace is atomic and
    # overwrites an existing *.migrated (os.rename raises FileExistsError on
    # Windows if the destination already exists).
    session.commit()
    for path in to_rename:
        os.replace(path, path + ".migrated")

    return result
