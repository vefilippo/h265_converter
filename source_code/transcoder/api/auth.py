from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from transcoder.config import settings

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    password: str


def require_auth(request: Request) -> None:
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="authentication required")


@router.post("/login")
def login(body: LoginIn, request: Request):
    if body.password != settings.APP_PASSWORD:
        raise HTTPException(status_code=401, detail="invalid password")
    request.session["authed"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {"authed": bool(request.session.get("authed"))}
