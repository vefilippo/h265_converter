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
from transcoder.api.routers import settings as settings_router

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

        # Seed settings from env on first startup
        import bcrypt as _bcrypt
        from transcoder.repo import seed_settings_from_env, get_setting, set_setting
        from transcoder.db import SessionLocal as _SL
        _cfg = settings  # settings is already imported from transcoder.config
        with _SL() as _db:
            seed_settings_from_env(_db, {
                "sonarr_url": _cfg.SONARR_URL,
                "sonarr_api_key": _cfg.SONARR_API_KEY,
                "radarr_url": _cfg.RADARR_URL,
                "radarr_api_key": _cfg.RADARR_API_KEY,
                "sftp_host": _cfg.SFTP_HOST,
                "sftp_port": str(_cfg.SFTP_PORT),
                "sftp_username": _cfg.SFTP_USERNAME,
                "sftp_password": _cfg.SFTP_PASSWORD,
                "handbrake_cli": _cfg.HANDBRAKE_CLI,
                "handbrake_preset_1080": _cfg.PRESET_1080,
                "handbrake_preset_4k": _cfg.PRESET_4K,
            })
            if get_setting(_db, "app_password_hash") is None and _cfg.APP_PASSWORD:
                _hash = _bcrypt.hashpw(_cfg.APP_PASSWORD.encode(), _bcrypt.gensalt()).decode()
                set_setting(_db, "app_password_hash", _hash)
                _db.commit()
            _sched_cron = get_setting(_db, "scheduler_cron")
            _sched_startup = get_setting(_db, "scheduler_run_at_startup") == "true"

        # Define the scheduled job (same logic as POST /run)
        async def _scheduled_run():
            import asyncio
            from transcoder.api.routers.scan import _run_full
            if not state.scan_status.try_start():
                log.info("Scheduled run skipped: scan already running")
                return
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _run_full)

        state.scheduler.set_job_fn(_scheduled_run)
        state.scheduler.start(_sched_cron, _sched_startup)

        try:
            yield
        finally:
            state.scheduler.shutdown()
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
    app.include_router(settings_router.router, dependencies=protected)

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
