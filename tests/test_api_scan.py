import transcoder.api.routers.scan as scan_mod
from transcoder.api import state


def test_scan_runs_and_reports_status(api, monkeypatch):
    client, Session = api
    calls = {}

    def fake_discover_sonarr(session, client_unused, scope="all", target_title=None):
        calls["sonarr"] = (scope, target_title)
        return 7

    def fake_discover_radarr(session, client_unused, target_movie=None):
        calls["radarr"] = target_movie
        return 3

    monkeypatch.setattr(scan_mod, "discover_sonarr", fake_discover_sonarr)
    monkeypatch.setattr(scan_mod, "discover_radarr", fake_discover_radarr)
    monkeypatch.setattr(scan_mod, "build_clients", lambda: {"sonarr": object(), "radarr": object()})
    monkeypatch.setattr(scan_mod, "SessionLocal", Session)
    state.scan_status.set("idle")

    r = client.post("/api/scan", json={"app": "all", "scope": "all"})
    assert r.status_code == 202

    # TestClient runs BackgroundTasks synchronously after the response is sent
    snap = state.scan_status.snapshot()
    assert snap["state"] == "done"
    assert snap["detail"]["sonarr"] == 7
    assert snap["detail"]["radarr"] == 3
    assert calls["sonarr"] == ("all", None)


def test_scan_conflict_when_running(api):
    client, Session = api
    state.scan_status.set("running")
    r = client.post("/api/scan", json={"app": "all", "scope": "all"})
    assert r.status_code == 409
    state.scan_status.set("idle")


def test_scan_status_try_start_is_atomic():
    from transcoder.api.state import ScanStatus
    s = ScanStatus()
    assert s.try_start() is True       # idle -> running
    assert s.running is True
    assert s.try_start() is False      # already running, second caller refused
    s.set("done")
    assert s.try_start() is True       # done -> running again is allowed


def test_scan_status_endpoint(api):
    client, Session = api
    state.scan_status.set("idle")
    r = client.get("/api/scan/status")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"
