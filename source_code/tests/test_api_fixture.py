def test_api_fixture_isolated(api):
    client, Session = api
    # health works through the fixture-built app
    assert client.get("/api/health").json() == {"status": "ok"}
    # the in-memory DB is empty + usable
    from transcoder.models import MediaItem
    s = Session()
    assert s.query(MediaItem).count() == 0
    s.close()
