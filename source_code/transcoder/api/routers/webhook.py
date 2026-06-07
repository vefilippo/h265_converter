import base64
import binascii
import hmac
import logging
import threading

import bcrypt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from transcoder.api.state import build_clients, controller
from transcoder.db import SessionLocal
from transcoder.engine.discovery import discover_sonarr, discover_radarr
from transcoder.engine.queue import enqueue_eligible
from transcoder.repo import get_setting

log = logging.getLogger("transcoder")

router = APIRouter(prefix="/api")

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


# Intentional module-level state: in-flight set used to coalesce duplicate webhooks for the same (source, title).
_pending: set[tuple[str, str]] = set()
_pending_lock = threading.Lock()


def _process_webhook(source: str, title: str) -> None:
    """Targeted discover + enqueue for a single title, then wake the worker.

    A burst of webhooks for the same (source, title) is coalesced: while one is
    in flight, duplicates return immediately (the in-flight discover re-scans the
    whole series/movie anyway)."""
    key = (source, title)
    with _pending_lock:
        if key in _pending:
            log.info("Webhook coalesced: (%s) %s already pending", source, title)
            return
        _pending.add(key)
    try:
        clients = build_clients()
        session = SessionLocal()
        try:
            if source == "sonarr":
                discover_sonarr(session, clients["sonarr"], scope="all", target_title=title)
            else:
                discover_radarr(session, clients["radarr"], target_movie=title)
            created = enqueue_eligible(session, source=source)
        finally:
            session.close()
        controller.wake()
        log.info("Webhook processed: source=%s title=%s enqueued=%d", source, title, created)
    except Exception:  # noqa: BLE001
        log.exception("Webhook processing failed: source=%s title=%s", source, title)
    finally:
        with _pending_lock:
            _pending.discard(key)


@router.post("/webhook/{source}")
async def receive_webhook(source: str, request: Request, background: BackgroundTasks):
    verify_webhook_auth(request)
    if source not in ("sonarr", "radarr"):
        raise HTTPException(404, "unknown source")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid JSON body")

    if payload.get("eventType") != "Download":
        return {"status": "ignored", "event": payload.get("eventType")}

    title = extract_title(source, payload)
    if not title:
        log.warning("Webhook %s import event with no title in payload", source)
        return {"status": "ignored", "reason": "no title"}

    background.add_task(_process_webhook, source, title)
    return {"status": "accepted", "title": title}
