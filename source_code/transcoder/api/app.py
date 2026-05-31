import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from starlette.middleware.sessions import SessionMiddleware

from transcoder.logging_setup import init_logging
from transcoder.db import SessionLocal, init_db, ensure_job_columns, backup_db
from transcoder.migrate import migrate_legacy
from transcoder.engine.worker import reconcile_stale_jobs
from transcoder.api import state
from transcoder.config import settings
from transcoder.api.auth import router as auth_router, require_auth

log = logging.getLogger("transcoder")


def create_app(start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_logging("api")
        init_db()
        backup_db()
        ensure_job_columns()
        session = SessionLocal()
        try:
            migrate_legacy(session)
            # Recover jobs orphaned in 'running' by a previous crash/restart so
            # they re-queue instead of sitting stuck forever.
            reconcile_stale_jobs(session)
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
    from transcoder.api.routers import library, scan, jobs, exclusions, stream, logs
    protected = [Depends(require_auth)]
    app.include_router(library.router, dependencies=protected)
    app.include_router(scan.router, dependencies=protected)
    app.include_router(jobs.router, dependencies=protected)
    app.include_router(exclusions.router, dependencies=protected)
    app.include_router(stream.router, dependencies=protected)
    app.include_router(logs.router, dependencies=protected)

    import os
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    dist = settings.WEB_DIST
    index_html = os.path.join(dist, "index.html")
    if os.path.isfile(index_html):
        assets_dir = os.path.join(dist, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str, request: Request):
            # API paths must never fall through to the SPA shell.
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = os.path.join(dist, full_path)
            if full_path and os.path.isfile(candidate):
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app
