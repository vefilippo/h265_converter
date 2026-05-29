from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from transcoder.api.deps import get_session
from transcoder.api.schemas import ExclusionIn, ExclusionOut
from transcoder.models import Exclusion

router = APIRouter(prefix="/api")


@router.get("/exclusions", response_model=list[ExclusionOut])
def list_exclusions(session: Session = Depends(get_session)):
    rows = session.query(Exclusion).order_by(Exclusion.id).all()
    return [ExclusionOut.model_validate(r) for r in rows]


@router.post("/exclusions", response_model=ExclusionOut, status_code=201)
def add_exclusion(body: ExclusionIn, session: Session = Depends(get_session)):
    existing = session.query(Exclusion).filter_by(source=body.source, key=body.key).first()
    if existing:
        raise HTTPException(status_code=409, detail="exclusion already exists")
    row = Exclusion(source=body.source, key=body.key, reason=body.reason)
    session.add(row)
    session.commit()
    session.refresh(row)
    return ExclusionOut.model_validate(row)


@router.delete("/exclusions/{exclusion_id}", status_code=204)
def delete_exclusion(exclusion_id: int, session: Session = Depends(get_session)):
    row = session.get(Exclusion, exclusion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="exclusion not found")
    session.delete(row)
    session.commit()
    return Response(status_code=204)
