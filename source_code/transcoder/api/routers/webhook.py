import base64
import binascii
import hmac
import logging

import bcrypt
from fastapi import HTTPException, Request

from transcoder.db import SessionLocal
from transcoder.repo import get_setting

log = logging.getLogger("transcoder")

_UNAUTH = {"WWW-Authenticate": "Basic"}


def _load_creds() -> tuple[str | None, str | None]:
    """Read the configured webhook username + bcrypt password hash."""
    # Per-request DB read is intentional: rotated credentials take effect immediately
    # without a restart (low-frequency endpoint; mirrors the auth.py login pattern).
    with SessionLocal() as db:
        return (
            get_setting(db, "webhook_username"),
            get_setting(db, "webhook_password_hash"),
        )


def verify_webhook_auth(request: Request) -> None:
    """Enforce HTTP Basic auth against the stored webhook credentials.
    Raises 401 (with a WWW-Authenticate header) on any failure."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        raise HTTPException(401, "authentication required", headers=_UNAUTH)
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(401, "authentication required", headers=_UNAUTH)
    username, _, password = decoded.partition(":")

    stored_user, stored_hash = _load_creds()
    # Must precede hmac.compare_digest / bcrypt.checkpw: both require non-None operands.
    if not stored_user or not stored_hash:
        raise HTTPException(401, "authentication required", headers=_UNAUTH)

    user_ok = hmac.compare_digest(username, stored_user)
    pass_ok = bcrypt.checkpw(password.encode(), stored_hash.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(401, "authentication required", headers=_UNAUTH)


def extract_title(source: str, payload: dict) -> str | None:
    """Pull the series/movie title out of a Sonarr/Radarr webhook payload.

    Returns None when the expected object is absent (e.g. a Test event)."""
    if source == "sonarr":
        return (payload.get("series") or {}).get("title")
    if source == "radarr":
        return (payload.get("movie") or {}).get("title")
    return None
