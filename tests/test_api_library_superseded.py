"""The Library reads as current state, not as an append-only file history.

`reap_orphans` marks rows whose Sonarr episodeFile is gone as "superseded"
rather than deleting them, because job rows reference them. 592 of 6206 rows on
the production install are in that state, and showing them puts a dead
duplicate next to every upgraded episode. So the default listing hides them,
and they stay reachable by asking for them explicitly.
"""

from transcoder.models import MediaItem


def _seed(Session):
    s = Session()
    s.add_all([
        MediaItem(source="sonarr", external_id="1", title="A", season=1, episode=1,
                  resolution=1080, remote_path="/old.mkv", eligibility="superseded"),
        MediaItem(source="sonarr", external_id="2", title="A", season=1, episode=1,
                  resolution=1080, remote_path="/new.mkv", eligibility="already_h265"),
        MediaItem(source="sonarr", external_id="3", title="B", season=1, episode=1,
                  resolution=1080, remote_path="/b.mkv", eligibility="needs_transcode"),
    ])
    s.commit()
    s.close()


def test_default_listing_hides_superseded_rows(api):
    client, Session = api
    _seed(Session)

    body = client.get("/api/library").json()

    assert body["total"] == 2
    assert {i["external_id"] for i in body["items"]} == {"2", "3"}


def test_superseded_rows_are_reachable_by_asking_for_them(api):
    client, Session = api
    _seed(Session)

    body = client.get("/api/library", params={"eligibility": "superseded"}).json()

    assert body["total"] == 1
    assert body["items"][0]["external_id"] == "1"


def test_other_filters_still_hide_superseded_rows(api):
    client, Session = api
    _seed(Session)

    body = client.get("/api/library", params={"source": "sonarr"}).json()
    assert body["total"] == 2

    body = client.get("/api/library", params={"q": "A"}).json()
    assert body["total"] == 1
    assert body["items"][0]["external_id"] == "2"


def test_stats_still_count_superseded_rows(api):
    # The Dashboard breakdown should account for every row, so the reap's work
    # is visible rather than silently vanishing from the totals.
    client, Session = api
    _seed(Session)

    stats = client.get("/api/library/stats").json()["stats"]
    superseded = [r for r in stats if r["eligibility"] == "superseded"]

    assert len(superseded) == 1
    assert superseded[0]["count"] == 1
