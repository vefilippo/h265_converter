from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from transcoder.api.deps import get_session
from transcoder.api.schemas import ExclusionIn, ExclusionOut, PruneOut
from transcoder.models import Exclusion, MediaItem, episode_exclusion_key

router = APIRouter(prefix="/api")


def _media_keys(session: Session) -> dict[str, set[str]]:
    """Build the set of exclusion keys that CURRENTLY exist in the library, per
    source, so we can tell which exclusions match a real media item."""
    sonarr: set[str] = set()
    radarr: set[str] = set()
    for mi in session.query(MediaItem).all():
        if mi.source == "sonarr":
            sonarr.add(episode_exclusion_key(mi.title, mi.season, mi.episode))
        else:
            radarr.add(mi.title)
    return {"sonarr": sonarr, "radarr": radarr}


def _is_orphan(row: Exclusion, keys: dict[str, set[str]]) -> bool:
    return row.key not in keys.get(row.source, set())


@router.get("/exclusions", response_model=list[ExclusionOut])
def list_exclusions(session: Session = Depends(get_session)):
    keys = _media_keys(session)
    rows = session.query(Exclusion).order_by(Exclusion.id).all()
    return [
        ExclusionOut(id=r.id, source=r.source, key=r.key, reason=r.reason,
                     matched=not _is_orphan(r, keys))
        for r in rows
    ]


@router.post("/exclusions", response_model=ExclusionOut, status_code=201)
def add_exclusion(body: ExclusionIn, session: Session = Depends(get_session)):
    existing = session.query(Exclusion).filter_by(source=body.source, key=body.key).first()
    if existing:
        raise HTTPException(status_code=409, detail="exclusion already exists")
    row = Exclusion(source=body.source, key=body.key, reason=body.reason)
    session.add(row)
    session.commit()
    session.refresh(row)
    keys = _media_keys(session)
    return ExclusionOut(id=row.id, source=row.source, key=row.key, reason=row.reason,
                        matched=not _is_orphan(row, keys))


@router.post("/exclusions/prune", response_model=PruneOut)
def prune_exclusions(session: Session = Depends(get_session)):
    """Remove exclusions that no longer match any item in the library
    (orphans, e.g. after a movie was renamed or left the non-H.265 set)."""
    keys = _media_keys(session)
    removed = 0
    for r in session.query(Exclusion).all():
        if _is_orphan(r, keys):
            session.delete(r)
            removed += 1
    session.commit()
    return PruneOut(removed=removed)


@router.delete("/exclusions/{exclusion_id}", status_code=204)
def delete_exclusion(exclusion_id: int, session: Session = Depends(get_session)):
    row = session.get(Exclusion, exclusion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="exclusion not found")
    session.delete(row)
    session.commit()
    return Response(status_code=204)
