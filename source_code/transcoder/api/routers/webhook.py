import logging

log = logging.getLogger("transcoder")


def extract_title(source: str, payload: dict) -> str | None:
    """Pull the series/movie title out of a Sonarr/Radarr webhook payload.

    Returns None when the expected object is absent (e.g. a Test event)."""
    if source == "sonarr":
        return (payload.get("series") or {}).get("title")
    if source == "radarr":
        return (payload.get("movie") or {}).get("title")
    return None
