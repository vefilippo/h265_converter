import zipfile
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from transcoder.api.auth import require_auth
from transcoder.config import settings
from transcoder.backup import make_backup, read_backup, db_path_from_url
from transcoder.restore import stage_restore, schedule_relaunch

router = APIRouter(prefix="/api", tags=["backup"])

# cwd-relative .env (the server runs with cwd = the package dir, like tray.pyw).
ENV_PATH = ".env"


class BackupRequest(BaseModel):
    passphrase: str


def _base_dir(db_path: str) -> str:
    import os
    return os.path.dirname(os.path.abspath(db_path)) or "."


@router.post("/backup", dependencies=[Depends(require_auth)])
def create_backup(body: BackupRequest):
    db_path = db_path_from_url(settings.DATABASE_URL)
    try:
        blob = make_backup(db_path, ENV_PATH, body.passphrase)
    except Exception as exc:  # snapshot/encrypt failure
        raise HTTPException(status_code=500, detail=f"backup failed: {exc}")
    name = "h265-backup-" + datetime.now(timezone.utc).strftime("%Y%m%d") + ".zip"
    return Response(content=blob, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/restore", status_code=202, dependencies=[Depends(require_auth)])
async def restore_backup(file: UploadFile = File(...), passphrase: str = Form(...)):
    _MAX_UPLOAD = 1024 * 1024 * 1024  # 1 GiB
    if file.size is not None and file.size > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="backup file too large")
    zip_bytes = await file.read()
    try:
        db_bytes, env_text, _manifest = read_backup(zip_bytes, passphrase)
    except (ValueError, KeyError, zipfile.BadZipFile, InvalidTag):
        raise HTTPException(status_code=400, detail="wrong passphrase or corrupt backup")
    db_path = db_path_from_url(settings.DATABASE_URL)
    stage_restore(db_bytes, env_text, _base_dir(db_path))
    schedule_relaunch(port=settings.API_PORT)
    return {"status": "restarting"}
