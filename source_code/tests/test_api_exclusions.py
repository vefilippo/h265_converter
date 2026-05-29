from transcoder.models import Exclusion


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
