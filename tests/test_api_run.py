from transcoder.models import Job, MediaItem


def _seed_eligible(Session):
    s = Session()
    s.add(MediaItem(source="sonarr", external_id="1", title="A", season=1, episode=1,
                    remote_path="/x", resolution=1080, eligibility="needs_transcode"))
    s.commit()
    s.close()


def test_run_scans_then_enqueues(api, monkeypatch):
    client, Session = api
    import transcoder.api.routers.scan as scan_router

    # Avoid real Sonarr/Radarr network calls: stub client build + discovery.
    monkeypatch.setattr(scan_router, "build_clients", lambda: {"sonarr": None, "radarr": None})
    monkeypatch.setattr(scan_router, "discover_sonarr", lambda *a, **k: 0)
    monkeypatch.setattr(scan_router, "discover_radarr", lambda *a, **k: 0)
    # The run flow opens its own session via SessionLocal imported into the
    # scan router; point that at the in-memory test DB.
    monkeypatch.setattr(scan_router, "SessionLocal", Session)

    _seed_eligible(Session)

    # TestClient runs the BackgroundTask synchronously before returning control.
    r = client.post("/api/run")
    assert r.status_code == 202

    # The eligible item was enqueued by the run flow.
    s = Session()
    assert s.query(Job).filter_by(state="queued").count() == 1
    s.close()

    status = client.get("/api/scan/status").json()
    assert status["state"] == "done"
    assert status["detail"]["enqueued"] == 1


def test_run_conflicts_while_running(api, monkeypatch):
    client, _ = api
    import transcoder.api.state as api_state

    # Pretend a scan is already in progress.
    assert api_state.scan_status.try_start() is True
    try:
        r = client.post("/api/run")
        assert r.status_code == 409
    finally:
        api_state.scan_status.set("done")
