"""Shared data-access helpers for the transcoder engine.

All helpers operate within the caller's session and never commit; the caller is
responsible for transaction boundaries.
"""

from transcoder.models import Exclusion, MediaItem, Setting, utcnow

# Fields managed by the upsert itself — callers must not pass them in **fields.
_IDENTITY_FIELDS = frozenset({"id", "source", "external_id", "last_scanned_at"})


def upsert_media_item(session, *, source: str, external_id: str, **fields) -> MediaItem:
    item = (
        session.query(MediaItem)
        .filter_by(source=source, external_id=external_id)
        .one_or_none()
    )
    if item is None:
        item = MediaItem(source=source, external_id=external_id)
        session.add(item)
    for key, value in fields.items():
        if key in _IDENTITY_FIELDS:
            raise ValueError(
                f"upsert_media_item: '{key}' is managed by the upsert and "
                "must not be passed in **fields"
            )
        setattr(item, key, value)
    item.last_scanned_at = utcnow()
    # Flush so a newly-created row is visible to later upserts in the SAME
    # uncommitted run (e.g. Sonarr multi-episode files share one episodeFileId
    # and are visited under multiple episodes). Without this, an autoflush=False
    # session would not see the pending insert and would create a duplicate,
    # violating the (source, external_id) unique constraint at commit.
    session.flush()
    return item


def get_setting(session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def set_setting(session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    # Flush so a repeat get/set in the same uncommitted (autoflush=False) run
    # sees this write instead of inserting a duplicate primary key.
    session.flush()


def excluded_keys(session, source: str) -> set[str]:
    return {
        e.key for e in session.query(Exclusion).filter_by(source=source).all()
    }
