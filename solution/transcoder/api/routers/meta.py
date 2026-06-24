from fastapi import APIRouter

from transcoder.version import read_version

router = APIRouter(prefix="/api")


@router.get("/version")
def version():
    return {"version": read_version()}
