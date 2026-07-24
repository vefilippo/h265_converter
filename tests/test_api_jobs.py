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
    # Timestamps are exposed so the Jobs view can show when a job ran.
    assert body["items"][0]["created_at"] is not None
    assert "started_at" in body["items"][0]
    assert "finished_at" in body["items"][0]


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


def test_cancel_stale_running_job_marks_cancelled(api, monkeypatch):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="running"))
    s.commit()
    jid = s.query(Job).one().id
    s.close()

    # Controller is not running this job (stale 'running' row, e.g. after a
    # crash mid-transcode). Cancel should succeed and mark it cancelled, not 409.
    monkeypatch.setattr(api_state.controller, "_current_job_id", None)
    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"


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


def _seed_jobs(Session, states):
    """Create one media_item + job per state, returning job ids in insert order."""
    s = Session()
    ids = []
    for i, state in enumerate(states):
        item = MediaItem(source="sonarr", external_id=str(1000 + i), title=f"T{i}",
                         season=1, episode=i, remote_path=f"/x{i}", resolution=1080,
                         eligibility="needs_transcode")
        s.add(item); s.flush()
        job = Job(media_item_id=item.id, state=state)
        s.add(job); s.flush()
        ids.append(job.id)
    s.commit(); s.close()
    return ids


def test_list_jobs_returns_newest_first(api):
    client, Session = api
    _seed_jobs(Session, ["done", "done", "queued"])
    body = client.get("/api/jobs").json()
    ids = [j["id"] for j in body["items"]]
    assert ids == sorted(ids, reverse=True)


def test_list_jobs_paginates_beyond_limit(api):
    client, Session = api
    job_ids = _seed_jobs(Session, ["done"] * 5)
    page1 = client.get("/api/jobs?limit=2").json()
    assert page1["total"] == 5
    assert [j["id"] for j in page1["items"]] == [job_ids[4], job_ids[3]]
    page3 = client.get("/api/jobs?limit=2&offset=4").json()
    assert [j["id"] for j in page3["items"]] == [job_ids[0]]


def test_list_jobs_state_counts_cover_all_jobs_even_when_filtered(api):
    client, Session = api
    _seed_jobs(Session, ["done", "done", "queued", "failed"])
    body = client.get("/api/jobs?state_filter=queued&limit=1").json()
    assert body["total"] == 1
    assert body["state_counts"] == {"done": 2, "queued": 1, "failed": 1}


def test_jobs_list_includes_phase(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="running", phase="transcoding"))
    s.commit(); s.close()
    body = client.get("/api/jobs").json()
    assert body["items"][0]["phase"] == "transcoding"


def test_job_includes_season_and_episode(api):
    client, Session = api
    _seed_item(Session, title="Breaking Bad", season=2, episode=9)
    client.post("/api/enqueue", json={})
    body = client.get("/api/jobs").json()
    item = body["items"][0]
    assert item["title"] == "Breaking Bad"
    assert item["season"] == 2
    assert item["episode"] == 9


def test_movie_job_has_null_season_episode(api):
    client, Session = api
    _seed_item(Session, source="radarr", external_id="99", title="Inception",
               season=None, episode=None)
    client.post("/api/enqueue", json={})
    body = client.get("/api/jobs").json()
    item = body["items"][0]
    assert item["season"] is None
    assert item["episode"] is None


def test_job_logs_endpoint_returns_log(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add(Job(media_item_id=iid, state="done", log="line one\nline two"))
    s.commit(); jid = s.query(Job).one().id; s.close()
    r = client.get(f"/api/jobs/{jid}/logs")
    assert r.status_code == 200
    assert r.json()["log"] == "line one\nline two"


def test_job_logs_endpoint_404(api):
    client, _ = api
    assert client.get("/api/jobs/999/logs").status_code == 404


def test_delete_terminal_jobs(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add_all([
        Job(media_item_id=iid, state="done"),
        Job(media_item_id=iid, state="failed"),
        Job(media_item_id=iid, state="skipped_larger"),
        Job(media_item_id=iid, state="cancelled"),
    ])
    s.commit()
    ids = [j.id for j in s.query(Job).all()]
    s.close()

    r = client.post("/api/jobs/delete", json={"ids": ids})
    assert r.status_code == 200
    assert r.json() == {"deleted": 4, "skipped": 0}

    s = Session()
    assert s.query(Job).count() == 0
    s.close()


def test_delete_skips_active_and_missing(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add_all([
        Job(media_item_id=iid, state="queued"),
        Job(media_item_id=iid, state="running"),
        Job(media_item_id=iid, state="done"),
    ])
    s.commit()
    by_state = {j.state: j.id for j in s.query(Job).all()}
    s.close()

    # queued + running skipped, done deleted, id 99999 missing -> skipped
    ids = [by_state["queued"], by_state["running"], by_state["done"], 99999]
    r = client.post("/api/jobs/delete", json={"ids": ids})
    assert r.status_code == 200
    assert r.json() == {"deleted": 1, "skipped": 3}

    s = Session()
    remaining = {j.state for j in s.query(Job).all()}
    assert remaining == {"queued", "running"}
    s.close()
