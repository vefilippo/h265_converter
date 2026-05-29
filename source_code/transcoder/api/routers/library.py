from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from transcoder.api import state
from transcoder.api.deps import get_session
from transcoder.api.schemas import JobOut, LibraryPage, LibraryStats, MediaItemOut, StatRow
from transcoder.models import Job, MediaItem

router = APIRouter(prefix="/api")


@router.get("/library", response_model=LibraryPage)
def list_library(
    source: str | None = None,
    eligibility: str | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    query = session.query(MediaItem)
    if source:
        query = query.filter(MediaItem.source == source)
    if eligibility:
        query = query.filter(MediaItem.eligibility == eligibility)
    if q:
        query = query.filter(MediaItem.title.ilike(f"%{q}%"))
    total = query.count()
    # Order by title -> season -> episode so a series' episodes group together.
    rows = (
        query.order_by(MediaItem.title, MediaItem.season, MediaItem.episode)
        .limit(limit)
        .offset(offset)
        .all()
    )
    return LibraryPage(total=total, items=[MediaItemOut.model_validate(r) for r in rows])


@router.post("/library/{item_id}/enqueue", response_model=JobOut)
def enqueue_item(item_id: int, session: Session = Depends(get_session)):
    """Queue a transcode for one specific media item (not the whole source)."""
    item = session.get(MediaItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="media item not found")
    # Return the existing active job if one is already queued/running.
    active = (
        session.query(Job)
        .filter(Job.media_item_id == item.id, Job.state.in_(["queued", "running"]))
        .first()
    )
    if active is not None:
        out = JobOut.model_validate(active)
        out.title = item.title
        return out
    if item.eligibility != "needs_transcode":
        raise HTTPException(
            status_code=409,
            detail=f"item eligibility is {item.eligibility}, not needs_transcode",
        )
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()
    state.controller.wake()
    session.refresh(job)
    out = JobOut.model_validate(job)
    out.title = item.title
    return out


@router.get("/library/stats", response_model=LibraryStats)
def library_stats(session: Session = Depends(get_session)):
    rows = (
        session.query(MediaItem.source, MediaItem.eligibility, func.count())
        .group_by(MediaItem.source, MediaItem.eligibility)
        .all()
    )
    return LibraryStats(stats=[StatRow(source=s, eligibility=e, count=c) for s, e, c in rows])
