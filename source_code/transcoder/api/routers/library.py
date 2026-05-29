from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from transcoder.api.deps import get_session
from transcoder.api.schemas import LibraryPage, LibraryStats, MediaItemOut, StatRow
from transcoder.models import MediaItem

router = APIRouter(prefix="/api")


@router.get("/library", response_model=LibraryPage)
def list_library(
    source: str | None = None,
    eligibility: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    q = session.query(MediaItem)
    if source:
        q = q.filter(MediaItem.source == source)
    if eligibility:
        q = q.filter(MediaItem.eligibility == eligibility)
    total = q.count()
    rows = q.order_by(MediaItem.id).limit(limit).offset(offset).all()
    return LibraryPage(total=total, items=[MediaItemOut.model_validate(r) for r in rows])


@router.get("/library/stats", response_model=LibraryStats)
def library_stats(session: Session = Depends(get_session)):
    rows = (
        session.query(MediaItem.source, MediaItem.eligibility, func.count())
        .group_by(MediaItem.source, MediaItem.eligibility)
        .all()
    )
    return LibraryStats(stats=[StatRow(source=s, eligibility=e, count=c) for s, e, c in rows])
