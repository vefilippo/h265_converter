from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from transcoder import config as _cfg
from transcoder import encoders
from transcoder.api.deps import get_session as get_db
from transcoder.repo import get_effective

router = APIRouter(prefix="/api/encoders", tags=["encoders"])


class DetectBody(BaseModel):
    # Lets the setup wizard detect against a path the user has typed but not
    # yet saved, mirroring POST /api/settings/test/{service}.
    handbrake_cli: str | None = None


class EncoderFamilyOut(BaseModel):
    id: str
    label: str
    preset_1080: str
    preset_4k: str
    hardware: bool
    available: bool


class EncodersOut(BaseModel):
    available: list[str]
    detected_at: str | None = None
    families: list[EncoderFamilyOut]


class DetectOut(EncodersOut):
    ok: bool
    error: str | None = None


def _payload(available: set[str], detected_at: str | None) -> dict:
    return {
        "available": sorted(available),
        "detected_at": detected_at,
        "families": [
            {
                "id": fid,
                "label": meta["label"],
                "preset_1080": meta["preset_1080"],
                "preset_4k": meta["preset_4k"],
                "hardware": meta["hardware"],
                "available": fid in available,
            }
            for fid, meta in encoders.FAMILIES.items()
        ],
    }


@router.get("", response_model=EncodersOut)
def list_encoders(db: Session = Depends(get_db)):
    """Catalog plus cached availability. Never shells out."""
    available, _unavailable, detected_at = encoders.load_capabilities(db)
    return _payload(available, detected_at)


@router.post("/detect", response_model=DetectOut)
def detect(body: DetectBody, db: Session = Depends(get_db)):
    """Probe HandBrake and cache the result."""
    cli = body.handbrake_cli or get_effective(db, "handbrake_cli", _cfg.settings.HANDBRAKE_CLI)
    if not cli:
        return {"ok": False, "error": "HandBrake CLI path is not set", **_payload(set(), None)}

    available, _unavailable, detected_at = encoders.detect_and_store(db, cli)
    if not available:
        return {
            "ok": False,
            "error": f"Could not run {cli}. Check the HandBrake CLI path.",
            **_payload(set(), None),
        }
    db.commit()
    return {"ok": True, **_payload(available, detected_at)}
