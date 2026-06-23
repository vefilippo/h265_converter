import bcrypt

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from transcoder.config import settings
from transcoder.repo import get_setting
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


@router.get("/me")
def me(request: Request):
    return {"authed": bool(request.session.get("authed"))}
