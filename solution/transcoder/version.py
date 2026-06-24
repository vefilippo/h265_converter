from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("transcoder")

# solution/transcoder/version.py -> solution/VERSION
_VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"

_FALLBACK = "0.0.0"


def read_version() -> str:
    try:
        return _VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        log.warning("VERSION file not readable at %s; using %s", _VERSION_PATH, _FALLBACK)
        return _FALLBACK
