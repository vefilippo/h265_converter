import datetime as dt, os
from .config import settings

def _parse_iso_z(s: str) -> dt.datetime:
    """Parse ``2025-07-18T04:03:52Z`` (or with offset) to a UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)

def load_last_history_date() -> dt.datetime | None:
    """Return stored watermark or ``None`` if missing/invalid."""
    try:
        with open(settings.LAST_HISTORY_FILE, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
        if raw:
            return _parse_iso_z(raw)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return None

def save_last_history_date(ts: dt.datetime) -> None:
    """Write latest timestamp in ISO-8601 Z format."""
    with open(settings.LAST_HISTORY_FILE, "w", encoding="utf-8") as fh:
        fh.write(ts.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"))

