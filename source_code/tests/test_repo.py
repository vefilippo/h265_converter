from transcoder.models import MediaItem, Exclusion
from transcoder import repo


def test_upsert_media_item_is_idempotent(session):
    repo.upsert_media_item(
        session, source="sonarr", external_id="7", title="A",
        remote_path="/TVShows/a.mkv", resolution=1080,
    )
    repo.upsert_media_item(
        session, source="sonarr", external_id="7", title="A (renamed)",
        remote_path="/TVShows/a.mkv", resolution=2160,
    )
    session.commit()
    items = session.query(MediaItem).all()
    assert len(items) == 1
    assert items[0].title == "A (renamed)"
    assert items[0].resolution == 2160


def test_setting_helpers(session):
    assert repo.get_setting(session, "k") is None
    repo.set_setting(session, "k", "v1")
    repo.set_setting(session, "k", "v2")
    assert repo.get_setting(session, "k") == "v2"


def test_excluded_keys(session):
    session.add(Exclusion(source="sonarr", key="A|1|1", reason="output_larger"))
    session.commit()
    assert repo.excluded_keys(session, "sonarr") == {"A|1|1"}
    assert repo.excluded_keys(session, "radarr") == set()
