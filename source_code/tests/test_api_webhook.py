from transcoder.api.routers.webhook import extract_title


def test_extract_title_sonarr():
    payload = {"eventType": "Download", "series": {"title": "Breaking Bad"}}
    assert extract_title("sonarr", payload) == "Breaking Bad"


def test_extract_title_radarr():
    payload = {"eventType": "Download", "movie": {"title": "Inception", "year": 2010}}
    assert extract_title("radarr", payload) == "Inception"


def test_extract_title_missing_returns_none():
    assert extract_title("sonarr", {"eventType": "Test"}) is None
    assert extract_title("radarr", {"movie": {}}) is None
    assert extract_title("sonarr", {"series": None}) is None


import base64
import bcrypt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import transcoder.api.routers.webhook as webhook


def _make_request(auth_header: str | None) -> Request:
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode()))
    scope = {"type": "http", "headers": headers}
    return Request(scope)


def _basic(user: str, pw: str) -> str:
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return f"Basic {token}"


def _seed_creds(monkeypatch, user="hookuser", pw="hookpass"):
    pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    store = {"webhook_username": user, "webhook_password_hash": pw_hash}
    monkeypatch.setattr(webhook, "_load_creds", lambda: (store["webhook_username"], store["webhook_password_hash"]))


def test_verify_auth_accepts_valid(monkeypatch):
    _seed_creds(monkeypatch)
    webhook.verify_webhook_auth(_make_request(_basic("hookuser", "hookpass")))


def test_verify_auth_rejects_wrong_password(monkeypatch):
    _seed_creds(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(_basic("hookuser", "WRONG")))
    assert exc.value.status_code == 401


def test_verify_auth_rejects_missing_header(monkeypatch):
    _seed_creds(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(None))
    assert exc.value.status_code == 401
    assert exc.value.headers.get("WWW-Authenticate") == "Basic"


def test_verify_auth_rejects_when_not_configured(monkeypatch):
    monkeypatch.setattr(webhook, "_load_creds", lambda: (None, None))
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(_basic("hookuser", "hookpass")))
    assert exc.value.status_code == 401
