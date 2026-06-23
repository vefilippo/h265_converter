from transcoder.models import Job, MediaItem


def _item(Session, **kw):
    s = Session()
    defaults = dict(source="sonarr", external_id="1", title="A", season=1, episode=1,
                    remote_path="/x", resolution=1080, eligibility="needs_transcode")
    defaults.update(kw)
    item = MediaItem(**defaults)
    s.add(item); s.commit()
    iid = item.id
    s.close()
    return iid


def test_enqueue_item_creates_job(api):
    client, Session = api
    iid = _item(Session)
    r = client.post(f"/api/library/{iid}/enqueue")
    assert r.status_code == 200
    assert r.json()["state"] == "queued"
    assert r.json()["title"] == "A"
    s = Session()
    assert s.query(Job).filter_by(media_item_id=iid).count() == 1
    s.close()


def test_enqueue_item_idempotent(api):
    client, Session = api
    iid = _item(Session)
    client.post(f"/api/library/{iid}/enqueue")
    client.post(f"/api/library/{iid}/enqueue")
    s = Session()
    assert s.query(Job).filter_by(media_item_id=iid).count() == 1  # not duplicated
    s.close()


def test_enqueue_item_not_eligible_409(api):
    client, Session = api
    iid = _item(Session, eligibility="already_h265")
    assert client.post(f"/api/library/{iid}/enqueue").status_code == 409


def test_enqueue_item_missing_404(api):
    client, Session = api
    assert client.post("/api/library/999/enqueue").status_code == 404
