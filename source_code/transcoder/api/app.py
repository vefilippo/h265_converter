import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from starlette.middleware.sessions import SessionMiddleware

from transcoder.logging_setup import init_logging
from transcoder.db import SessionLocal, init_db
from transcoder.migrate import migrate_legacy
from transcoder.api import state
from transcoder.config import settings
from transcoder.api.auth import router as auth_router, require_auth

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

    app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, same_site="lax")

    # Open: health (defined above) + auth.
    app.include_router(auth_router)

    # Protected API routers.
    from transcoder.api.routers import library, scan, jobs, exclusions, stream
    protected = [Depends(require_auth)]
    app.include_router(library.router, dependencies=protected)
    app.include_router(scan.router, dependencies=protected)
    app.include_router(jobs.router, dependencies=protected)
    app.include_router(exclusions.router, dependencies=protected)
    app.include_router(stream.router, dependencies=protected)
    return app
