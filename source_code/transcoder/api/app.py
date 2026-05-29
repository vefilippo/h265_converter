import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from transcoder.logging_setup import init_logging
from transcoder.db import SessionLocal, init_db
from transcoder.migrate import migrate_legacy
from transcoder.api import state

log = logging.getLogger("transcoder")


def create_app(start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_logging()
        init_db()
        session = SessionLocal()
        try:
            migrate_legacy(session)
        finally:
            session.close()
        if start_worker:
            state.controller.start()
        try:
            yield
        finally:
            if start_worker:
                state.controller.shutdown()

    app = FastAPI(title="H.265 Transcoder", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    from transcoder.api.routers import library, scan, jobs, exclusions, stream
    app.include_router(library.router)
    app.include_router(scan.router)
    app.include_router(jobs.router)
    app.include_router(exclusions.router)
    app.include_router(stream.router)
    return app
