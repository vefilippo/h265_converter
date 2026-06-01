import datetime as dt


def _parse_iso_z(s: str) -> dt.datetime:
    """Parse ``2025-07-18T04:03:52Z`` (or with offset) to a UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)
