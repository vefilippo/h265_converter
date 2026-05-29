import threading

from transcoder.api import state as api_state
from transcoder.models import Exclusion, Job, MediaItem


def _seed_item(Session, **kw):
    s = Session()
    defaults = dict(source="sonarr", external_id="1", title="A", season=1, episode=1,
                    remote_path="/x", resolution=1080, eligibility="needs_transcode")
    defaults.update(kw)
    item = MediaItem(**defaults)
    s.add(item); s.commit()
    iid = item.id
    s.close()
    return iid


def test_enqueue_and_list_jobs(api):
    client, Session = api
    _seed_item(Session)
    r = client.post("/api/enqueue", json={})
    assert r.status_code == 200
    assert r.json()["created"] == 1

    r = client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "queued"
    assert body["items"][0]["title"] == "A"


def test_cancel_queued_job(api):
    client, Session = api
    _seed_item(Session)
    client.post("/api/enqueue", json={})
    jid = client.get("/api/jobs").json()["items"][0]["id"]

    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"


def test_cancel_running_job_signals_controller(api, monkeypatch):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="running"))
    s.commit()
    jid = s.query(Job).one().id
    s.close()

    # Simulate the worker currently running this job.
    ev = threading.Event()
    monkeypatch.setattr(api_state.controller, "_current_job_id", jid)
    monkeypatch.setattr(api_state.controller, "_current_cancel", ev)

    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200
    # async cancel: state stays "running" until the worker flips it later
    assert r.json()["state"] == "running"
    # the controller was signalled to stop the in-flight transcode
    assert ev.is_set() is True


def test_cancel_running_job_not_on_worker_returns_409(api, monkeypatch):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="running"))
    s.commit()
    jid = s.query(Job).one().id
    s.close()

    # Controller is not running this job (stale 'running' row).
    monkeypatch.setattr(api_state.controller, "_current_job_id", None)
    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 409


def test_cancel_non_cancellable_state_returns_409(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="done"))
    s.commit()
    jid = s.query(Job).one().id
    s.close()

    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 409


def test_retry_failed_job_creates_new(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="failed"))
    s.commit()
    old_jid = s.query(Job).one().id
    s.close()

    r = client.post(f"/api/jobs/{old_jid}/retry")
    assert r.status_code == 200
    jobs = client.get("/api/jobs").json()["items"]
    states = sorted(j["state"] for j in jobs)
    assert states == ["failed", "queued"]


def test_retry_skipped_larger_clears_exclusion(api):
    client, Session = api
    iid = _seed_item(Session, eligibility="excluded")
    s = Session()
    s.add(Job(media_item_id=iid, state="skipped_larger"))
    s.add(Exclusion(source="sonarr", key="A|1|1", reason="output_larger"))
    s.commit()
    jid = s.query(Job).one().id
    s.close()

    r = client.post(f"/api/jobs/{jid}/retry")
    assert r.status_code == 200
    s = Session()
    assert s.query(Exclusion).count() == 0
    item = s.get(MediaItem, iid)
    assert item.eligibility == "needs_transcode"
    s.close()


def test_job_404(api):
    client, Session = api
    assert client.get("/api/jobs/999").status_code == 404
    assert client.post("/api/jobs/999/cancel").status_code == 404
    assert client.post("/api/jobs/999/retry").status_code == 404
