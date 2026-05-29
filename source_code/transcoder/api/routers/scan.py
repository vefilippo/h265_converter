import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from transcoder.api import state
from transcoder.api.schemas import ScanIn
from transcoder.api.state import build_clients
from transcoder.db import SessionLocal
from transcoder.engine.discovery import discover_sonarr, discover_radarr

router = APIRouter(prefix="/api")
log = logging.getLogger("transcoder")


def _run_scan(body: ScanIn):
    # State is already "running" (set atomically by start_scan via try_start()).
    detail = {}
    try:
        clients = build_clients()
        session = SessionLocal()
        try:
            if body.app in ("all", "sonarr"):
                detail["sonarr"] = discover_sonarr(
                    session, clients["sonarr"], scope=body.scope, target_title=body.show)
            if body.app in ("all", "radarr"):
                detail["radarr"] = discover_radarr(
                    session, clients["radarr"], target_movie=body.movie)
        finally:
            session.close()
        state.scan_status.set("done", **detail)
    except Exception as exc:  # noqa: BLE001
        log.exception("scan failed")
        state.scan_status.set("error", message=str(exc), **detail)


@router.post("/scan", status_code=202)
def start_scan(body: ScanIn, background: BackgroundTasks):
    # Atomic check-and-set avoids a TOCTOU race where two near-simultaneous
    # requests both pass the guard before either background task runs.
    if not state.scan_status.try_start():
        raise HTTPException(status_code=409, detail="a scan is already running")
    background.add_task(_run_scan, body)
    return {"status": "accepted"}


@router.get("/scan/status")
def scan_status():
    return state.scan_status.snapshot()
