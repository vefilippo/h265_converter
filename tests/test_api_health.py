from fastapi.testclient import TestClient

import transcoder.api.app as app_module
from transcoder.api.app import create_app


def test_health_ok(monkeypatch):
    # Keep the test hermetic: don't touch the real DB / migrate legacy files.
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
