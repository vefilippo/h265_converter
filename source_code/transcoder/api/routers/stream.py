import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from transcoder.api.deps import get_session
from transcoder.api import state
from transcoder.api.schemas import JobOut, StatRow, StatusOut
from transcoder.models import Job, MediaItem

router = APIRouter(prefix="/api")


def _stats(session: Session) -> list[StatRow]:
    rows = (session.query(MediaItem.source, MediaItem.eligibility, func.count())
            .group_by(MediaItem.source, MediaItem.eligibility).all())
    return [StatRow(source=s, eligibility=e, count=c) for s, e, c in rows]


def _current_job_out(session: Session) -> JobOut | None:
    jid = state.controller.current_job_id
    if jid is None:
        return None
    job = session.get(Job, jid, options=[joinedload(Job.media_item)])
    if job is None:
        return None
    out = JobOut.model_validate(job)
    out.title = job.media_item.title if job.media_item else None
    return out


@router.get("/status", response_model=StatusOut)
def status(session: Session = Depends(get_session)):
    queue_length = session.query(Job).filter(Job.state == "queued").count()
    return StatusOut(
        worker_alive=state.controller.is_alive(),
        current_job=_current_job_out(session),
        queue_length=queue_length,
        stats=_stats(session),
    )


@router.get("/stream")
def stream(max_events: int | None = None, session: Session = Depends(get_session)):
    async def gen():
        cur = _current_job_out(session)
        payload = cur.model_dump() if cur else None
        yield f"event: status\ndata: {json.dumps(payload)}\n\n"
        count = 1
        while max_events is None or count < max_events:
            await asyncio.sleep(1.0)
            # Drop the identity-map cache so the next read reflects the worker's
            # latest committed progress (sessions use expire_on_commit=False).
            session.expire_all()
            cur = _current_job_out(session)
            payload = cur.model_dump() if cur else None
            event = "progress" if cur else "heartbeat"
            yield f"event: {event}\ndata: {json.dumps(payload)}\n\n"
            count += 1

    return StreamingResponse(gen(), media_type="text/event-stream")
