from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from transcoder.api.deps import get_session
from transcoder.api import state
from transcoder.api.schemas import (
    EnqueueIn, EnqueueOut, JobDeleteIn, JobDeleteOut, JobLogOut, JobOut, JobPage,
)
from transcoder.engine.queue import enqueue_eligible
from transcoder.models import Exclusion, Job, episode_exclusion_key, movie_exclusion_key, utcnow

router = APIRouter(prefix="/api")

_RETRYABLE = {"failed", "skipped_larger", "cancelled"}
_DELETABLE = {"done", "failed", "skipped_larger", "cancelled"}


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    if job.media_item:
        out.title = job.media_item.title
        out.season = job.media_item.season
        out.episode = job.media_item.episode
    return out


def _get_job(session: Session, job_id: int) -> Job:
    # session.get forwards loader options in SQLAlchemy 2.0 (Query.get does not).
    job = session.get(Job, job_id, options=[joinedload(Job.media_item)])
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/enqueue", response_model=EnqueueOut)
def enqueue(body: EnqueueIn, session: Session = Depends(get_session)):
    created = enqueue_eligible(session, source=body.source)
    state.controller.wake()
    return EnqueueOut(created=created)


@router.get("/jobs", response_model=JobPage)
def list_jobs(
    state_filter: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    q = session.query(Job).options(joinedload(Job.media_item))
    if state_filter:
        q = q.filter(Job.state == state_filter)
    total = q.count()
    rows = q.order_by(Job.id).limit(limit).offset(offset).all()
    return JobPage(total=total, items=[_to_out(j) for j in rows])


@router.post("/jobs/delete", response_model=JobDeleteOut)
def delete_jobs(body: JobDeleteIn, session: Session = Depends(get_session)):
    deleted = 0
    skipped = 0
    for job_id in body.ids:
        job = session.get(Job, job_id)
        if job is not None and job.state in _DELETABLE:
            session.delete(job)
            deleted += 1
        else:
            skipped += 1
    session.commit()
    return JobDeleteOut(deleted=deleted, skipped=skipped)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)):
    return _to_out(_get_job(session, job_id))


@router.get("/jobs/{job_id}/logs", response_model=JobLogOut)
def get_job_logs(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    return JobLogOut(log=job.log or "")


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    if job.state == "running":
        if state.controller.current_job_id == job_id:
            # async cancel: worker kills the subprocess and flips state later
            state.controller.request_cancel(job_id)
        else:
            # Stale 'running' row: the worker isn't processing this job (e.g.
            # left over from a crash/restart mid-transcode). It's not actually
            # running, so cancel it directly instead of leaving it stuck and
            # un-cancellable.
            job.state = "cancelled"
            job.finished_at = utcnow()
            session.commit()
    elif job.state == "queued":
        job.state = "cancelled"
        session.commit()
    else:
        raise HTTPException(status_code=409, detail=f"job state {job.state} cannot be cancelled")
    session.refresh(job)
    return _to_out(job)


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, session: Session = Depends(get_session)):
    job = _get_job(session, job_id)
    if job.state not in _RETRYABLE:
        raise HTTPException(status_code=409, detail=f"job state {job.state} is not retryable")

    item = job.media_item
    # If it was skipped because the output was larger, clear that exclusion and
    # reset eligibility so the retry will actually run.
    if job.state == "skipped_larger":
        key = (episode_exclusion_key(item.title, item.season, item.episode)
               if item.source == "sonarr" else movie_exclusion_key(item.title))
        for ex in session.query(Exclusion).filter_by(source=item.source, key=key).all():
            session.delete(ex)
        item.eligibility = "needs_transcode"

    # Only create a new job if none is active.
    active = (session.query(Job)
              .filter(Job.media_item_id == item.id, Job.state.in_(["queued", "running"]))
              .first())
    new_job = active
    if active is None:
        new_job = Job(media_item_id=item.id, state="queued")
        session.add(new_job)
    # Commit unconditionally so exclusion deletes + eligibility reset (and the
    # new job, if any) are persisted before we refresh/return.
    session.commit()
    state.controller.wake()
    session.refresh(new_job)
    return _to_out(new_job)
