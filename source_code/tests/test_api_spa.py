from fastapi.testclient import TestClient
import transcoder.api.app as app_module
from transcoder.api.app import create_app


def test_spa_served_when_dist_exists(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module.settings, "WEB_DIST", str(dist))

    app = create_app(start_worker=False)
    with TestClient(app) as client:
        r = client.get("/library")
        assert r.status_code == 200 and "<title>app</title>" in r.text
        assert client.get("/assets/app.js").status_code == 200
        r404 = client.get("/api/does-not-exist")
        assert r404.status_code == 404
        assert "<title>app</title>" not in r404.text


def test_app_boots_without_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module.settings, "WEB_DIST", str(tmp_path / "missing"))
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
