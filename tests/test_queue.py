from transcoder.engine.queue import enqueue_eligible
from transcoder.models import Job, MediaItem


def _add(session, **kw):
    item = MediaItem(source="sonarr", remote_path="/x.mkv", **kw)
    session.add(item)
    session.commit()
    return item


def test_enqueue_only_eligible(session):
    _add(session, external_id="1", title="A", eligibility="needs_transcode")
    _add(session, external_id="2", title="B", eligibility="already_h265")
    _add(session, external_id="3", title="C", eligibility="below_1080p")
    created = enqueue_eligible(session)
    assert created == 1
    assert session.query(Job).count() == 1


def test_enqueue_dedupes_active_jobs(session):
    item = _add(session, external_id="1", title="A", eligibility="needs_transcode")
    session.add(Job(media_item_id=item.id, state="queued"))
    session.commit()
    created = enqueue_eligible(session)
    assert created == 0
    assert session.query(Job).count() == 1
