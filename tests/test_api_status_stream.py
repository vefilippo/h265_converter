from transcoder.models import Job, MediaItem


def _seed_queued(Session):
    s = Session()
    item = MediaItem(source="sonarr", external_id="1", title="A", resolution=1080,
                     remote_path="/x", eligibility="needs_transcode")
    s.add(item); s.commit()
    s.add(Job(media_item_id=item.id, state="queued"))
    s.commit()
    s.close()


def test_status_endpoint(api):
    client, Session = api
    _seed_queued(Session)
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["queue_length"] == 1
    assert body["worker_alive"] in (True, False)
    assert "stats" in body


def test_stream_emits_event(api):
    client, Session = api
    r = client.get("/api/stream", params={"max_events": 1})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "event:" in r.text
