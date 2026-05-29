"""Integration check: FastAPI serves the REAL built SPA when web/dist exists.

Skips when the frontend hasn't been built (web/dist absent), so the backend
suite stays green without a Node build.
"""
import os

import pytest
from fastapi.testclient import TestClient

import transcoder.api.app as app_module
from transcoder.api.app import create_app

_DIST = os.path.join("web", "dist")


@pytest.mark.skipif(
    not os.path.isfile(os.path.join(_DIST, "index.html")),
    reason="web/dist not built",
)
def test_real_spa_is_served(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module.settings, "WEB_DIST", _DIST)
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        # SPA shell for a client route
        root = client.get("/")
        assert root.status_code == 200
        assert "<!doctype html>" in root.text.lower()
        # an unknown API path still returns JSON 404, not the shell
        assert client.get("/api/nope").status_code == 404
