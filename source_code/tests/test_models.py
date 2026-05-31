from transcoder.models import (
    MediaItem, Job, Exclusion, Setting,
    episode_exclusion_key, movie_exclusion_key,
)


def test_exclusion_key_helpers():
    assert episode_exclusion_key("Breaking Bad", 3, 5) == "Breaking Bad|3|5"
    assert movie_exclusion_key("Inception") == "Inception"


def test_can_persist_media_item_and_job(session):
    item = MediaItem(
        source="sonarr", external_id="42", title="Breaking Bad",
        season=1, episode=1, remote_path="/TVShows/x.mkv",
        resolution=1080, eligibility="needs_transcode",
    )
    session.add(item)
    session.commit()
    job = Job(media_item_id=item.id, state="queued", progress=0)
    session.add(job)
    session.commit()
    assert job.id is not None
    assert job.media_item.title == "Breaking Bad"


def test_setting_roundtrip(session):
    session.add(Setting(key="sonarr_watermark", value="2025-01-01T00:00:00Z"))
    session.commit()
    assert session.get(Setting, "sonarr_watermark").value == "2025-01-01T00:00:00Z"


def test_job_has_phase_and_log_columns(session):
    from transcoder.models import Job, MediaItem
    item = MediaItem(source="sonarr", external_id="1", title="A", season=1,
                     episode=1, remote_path="/x", resolution=1080,
                     eligibility="needs_transcode")
    session.add(item); session.commit()
    job = Job(media_item_id=item.id, state="running", phase="downloading", log="hi")
    session.add(job); session.commit()
    fetched = session.query(Job).one()
    assert fetched.phase == "downloading"
    assert fetched.log == "hi"
