from transcoder.models import Exclusion, MediaItem


def test_exclusions_crud(api):
    client, Session = api
    # empty
    assert client.get("/api/exclusions").json() == []

    # create
    r = client.post("/api/exclusions", json={"source": "sonarr", "key": "A|1|1"})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert r.json()["reason"] == "manual"

    # list
    rows = client.get("/api/exclusions").json()
    assert len(rows) == 1 and rows[0]["key"] == "A|1|1"

    # duplicate -> 409
    dup = client.post("/api/exclusions", json={"source": "sonarr", "key": "A|1|1"})
    assert dup.status_code == 409

    # delete
    assert client.delete(f"/api/exclusions/{eid}").status_code == 204
    assert client.get("/api/exclusions").json() == []

    # delete missing -> 404
    assert client.delete("/api/exclusions/999").status_code == 404


def test_exclusions_matched_flag_and_prune(api):
    client, Session = api
    s = Session()
    # one sonarr episode present in the library...
    s.add(MediaItem(source="sonarr", external_id="1", title="Show A", season=1,
                    episode=1, remote_path="/x", resolution=1080, eligibility="excluded"))
    # ...with a matching exclusion, plus an orphan exclusion (no such item)
    s.add(Exclusion(source="sonarr", key="Show A|1|1", reason="output_larger"))
    s.add(Exclusion(source="radarr", key="Renamed Movie", reason="output_larger"))
    s.commit(); s.close()

    rows = {r["key"]: r["matched"] for r in client.get("/api/exclusions").json()}
    assert rows["Show A|1|1"] is True       # matches a library item
    assert rows["Renamed Movie"] is False   # orphan

    # prune removes only the orphan
    r = client.post("/api/exclusions/prune")
    assert r.status_code == 200
    assert r.json()["removed"] == 1
    keys = {r["key"] for r in client.get("/api/exclusions").json()}
    assert keys == {"Show A|1|1"}
