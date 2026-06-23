from transcoder.models import Job, MediaItem


def enqueue_eligible(session, source: str | None = None) -> int:
    query = session.query(MediaItem).filter(
        MediaItem.eligibility == "needs_transcode"
    )
    if source:
        query = query.filter(MediaItem.source == source)

    created = 0
    for item in query.all():
        active = (
            session.query(Job)
            .filter(Job.media_item_id == item.id, Job.state.in_(["queued", "running"]))
            .first()
        )
        if active:
            continue
        session.add(Job(media_item_id=item.id, state="queued"))
        created += 1

    session.commit()
    return created
