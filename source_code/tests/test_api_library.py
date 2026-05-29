from transcoder.models import MediaItem


def _seed(Session):
    s = Session()
    s.add_all([
        MediaItem(source="sonarr", external_id="1", title="A", resolution=1080,
                  remote_path="/x", eligibility="needs_transcode"),
        MediaItem(source="sonarr", external_id="2", title="B", resolution=720,
                  remote_path="/y", eligibility="below_1080p"),
        MediaItem(source="radarr", external_id="3", title="C", resolution=2160,
                  remote_path="/z", eligibility="already_h265"),
    ])
    s.commit()
    s.close()


def test_library_list_and_filter(api):
    client, Session = api
    _seed(Session)

    r = client.get("/api/library")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3

    r = client.get("/api/library", params={"source": "sonarr"})
    assert r.json()["total"] == 2

    r = client.get("/api/library", params={"eligibility": "already_h265"})
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["title"] == "C"


def test_library_stats(api):
    client, Session = api
    _seed(Session)
    r = client.get("/api/library/stats")
    assert r.status_code == 200
    stats = r.json()["stats"]
    pairs = {(s["source"], s["eligibility"]): s["count"] for s in stats}
    assert pairs[("sonarr", "needs_transcode")] == 1
    assert pairs[("radarr", "already_h265")] == 1
