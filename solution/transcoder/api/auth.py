import bcrypt

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from transcoder.config import settings
from transcoder.repo import get_setting, set_setting
from transcoder.db import SessionLocal

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    password: str


def require_auth(request: Request) -> None:
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="authentication required")


@router.post("/login")
def login(body: LoginIn, request: Request):
    password = body.password
    with SessionLocal() as db:
        stored_hash = get_setting(db, "app_password_hash")
    if stored_hash:
        if not bcrypt.checkpw(password.encode(), stored_hash.encode()):
            raise HTTPException(status_code=401, detail="Invalid password")
    else:
        if password != settings.APP_PASSWORD:
            raise HTTPException(status_code=401, detail="Invalid password")
    request.session["authed"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


def _password_configured(db) -> bool:
    """True once a login password exists — a stored hash or a non-empty env
    APP_PASSWORD. Drives first-run detection."""
    return get_setting(db, "app_password_hash") is not None or bool(settings.APP_PASSWORD)


@router.get("/me")
def me(request: Request):
    with SessionLocal() as db:
        configured = _password_configured(db)
    return {"authed": bool(request.session.get("authed")), "needs_setup": not configured}


class SetupPasswordIn(BaseModel):
    password: str


@router.post("/setup/password")
def setup_password(body: SetupPasswordIn, request: Request):
    """Set the initial dashboard password on a fresh install. Open (no auth)
    but allowed ONLY while no password exists, so it can't hijack a configured
    instance. On success, log the caller in."""
    if not body.password.strip():
        raise HTTPException(status_code=422, detail="Password required")
    with SessionLocal() as db:
        if _password_configured(db):
            raise HTTPException(status_code=409, detail="Already configured")
        new_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        set_setting(db, "app_password_hash", new_hash)
        db.commit()
    request.session["authed"] = True
    return {"ok": True}
