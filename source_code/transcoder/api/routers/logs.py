from fastapi import APIRouter

from transcoder.api.schemas import LogLine, LogPage
from transcoder.log_buffer import log_buffer

router = APIRouter(prefix="/api")


@router.get("/logs", response_model=LogPage)
def get_logs(after: int = 0):
    rows = log_buffer.after(after)
    last = rows[-1]["seq"] if rows else after
    return LogPage(lines=[LogLine(**r) for r in rows], last_seq=last)
