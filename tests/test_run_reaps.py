"""A run reaps orphaned media_item rows between discovery and enqueue.

Order matters. Discovery is what creates the second row for an episode whose
file Sonarr replaced, so reaping *after* it lets the same run retire the row
that scan just superseded, instead of leaving it live until the next run. And
reaping before `enqueue_eligible` is what stops an orphan still marked
needs_transcode from being queued one last time.

`scan` stays discovery-only and must not reap.
"""

import sys

import transcoder.cli as cli_module
import transcoder.models  # noqa: F401  (registers tables on Base)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from transcoder.db import Base


def _recorder(order, name, result=0):
    def fn(*args, **kwargs):
        order.append(name)
        return result
    return fn


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _patch_run_flow(monkeypatch, scan_router, Session, order, sonarr=None, reaped=0):
    clients = {"sonarr": sonarr or object(), "radarr": object()}
    monkeypatch.setattr(scan_router, "build_clients", lambda: clients)
    monkeypatch.setattr(scan_router, "SessionLocal", Session)
    monkeypatch.setattr(scan_router, "discover_sonarr", _recorder(order, "discover_sonarr"))
    monkeypatch.setattr(scan_router, "discover_radarr", _recorder(order, "discover_radarr"))
    monkeypatch.setattr(scan_router, "reap_orphans", _recorder(order, "reap_orphans", reaped))
    monkeypatch.setattr(scan_router, "enqueue_eligible", _recorder(order, "enqueue_eligible"))
    return clients


def test_api_run_reaps_after_discovery_and_before_enqueue(api, monkeypatch):
    client, Session = api
    import transcoder.api.routers.scan as scan_router

    order = []
    _patch_run_flow(monkeypatch, scan_router, Session, order)

    assert client.post("/api/run").status_code == 202
    assert order == [
        "discover_sonarr", "discover_radarr", "reap_orphans", "enqueue_eligible",
    ]


def test_api_run_reports_how_many_rows_were_reaped(api, monkeypatch):
    client, Session = api
    import transcoder.api.routers.scan as scan_router

    _patch_run_flow(monkeypatch, scan_router, Session, [], reaped=592)

    client.post("/api/run")

    detail = client.get("/api/scan/status").json()["detail"]
    assert detail["reaped"] == 592


def test_api_run_reaps_with_the_sonarr_client(api, monkeypatch):
    client, Session = api
    import transcoder.api.routers.scan as scan_router

    sonarr = object()
    captured = {}

    def reap(session, reap_client, *args, **kwargs):
        captured["client"] = reap_client
        return 0

    _patch_run_flow(monkeypatch, scan_router, Session, [], sonarr=sonarr)
    monkeypatch.setattr(scan_router, "reap_orphans", reap)

    client.post("/api/run")
    assert captured["client"] is sonarr


def _patch_cli(monkeypatch, Session, order):
    monkeypatch.setattr(cli_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(cli_module, "init_logging", lambda *a, **k: None)
    monkeypatch.setattr(cli_module, "SessionLocal", Session)
    monkeypatch.setattr(cli_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(cli_module, "SonarrClient", lambda *a, **k: object())
    monkeypatch.setattr(cli_module, "RadarrClient", lambda *a, **k: object())
    monkeypatch.setattr(cli_module, "discover_sonarr", _recorder(order, "discover_sonarr"))
    monkeypatch.setattr(cli_module, "discover_radarr", _recorder(order, "discover_radarr"))
    monkeypatch.setattr(cli_module, "reap_orphans", _recorder(order, "reap_orphans"))
    monkeypatch.setattr(cli_module, "enqueue_eligible", _recorder(order, "enqueue_eligible"))
    monkeypatch.setattr(cli_module, "process_queue", _recorder(order, "process_queue"))


def test_cli_run_reaps_after_discovery_and_before_enqueue(monkeypatch):
    order = []
    _patch_cli(monkeypatch, _session_factory(), order)
    monkeypatch.setattr(sys, "argv", ["cli.py", "run", "all"])

    cli_module.main()

    assert order == [
        "discover_sonarr", "discover_radarr", "reap_orphans",
        "enqueue_eligible", "process_queue",
    ]


def test_cli_scan_does_not_reap(monkeypatch):
    # `scan` is discovery-only by contract; it must not mutate eligibility.
    order = []
    _patch_cli(monkeypatch, _session_factory(), order)
    monkeypatch.setattr(sys, "argv", ["cli.py", "scan", "all"])

    cli_module.main()

    assert order == ["discover_sonarr", "discover_radarr"]
