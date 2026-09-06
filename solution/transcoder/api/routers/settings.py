import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from transcoder.api.auth import require_auth
from transcoder.api.deps import get_session as get_db
from transcoder.api import state
from transcoder.api.schemas import SettingsOut, SettingsUpdate
from transcoder.repo import get_setting, set_setting, get_effective
from transcoder.scheduler import SchedulerController
from transcoder import config as _cfg

router = APIRouter(prefix="/api/settings", tags=["settings"])

_REDACTED = "••••••••"
_CREDENTIAL_KEYS = {
    "sonarr_api_key", "radarr_api_key",
    "sftp_password",
}


def _mask(db: Session, key: str, fallback: str = "") -> str:
    val = get_effective(db, key, fallback)
    return _REDACTED if val else ""


@router.get("", response_model=SettingsOut, dependencies=[Depends(require_auth)])
def get_settings(db: Session = Depends(get_db)):
    cfg = _cfg.settings
    return SettingsOut(
        scheduler_cron=get_setting(db, "scheduler_cron"),
        scheduler_run_at_startup=get_effective(db, "scheduler_run_at_startup", "false"),
        sonarr_url=get_effective(db, "sonarr_url", cfg.SONARR_URL),
        sonarr_api_key=_mask(db, "sonarr_api_key", cfg.SONARR_API_KEY),
        radarr_url=get_effective(db, "radarr_url", cfg.RADARR_URL),
        radarr_api_key=_mask(db, "radarr_api_key", cfg.RADARR_API_KEY),
        sftp_host=get_effective(db, "sftp_host", cfg.SFTP_HOST),
        sftp_port=get_effective(db, "sftp_port", str(cfg.SFTP_PORT)),
        sftp_username=get_effective(db, "sftp_username", cfg.SFTP_USERNAME),
        sftp_password=_mask(db, "sftp_password", cfg.SFTP_PASSWORD),
        handbrake_cli=get_effective(db, "handbrake_cli", cfg.HANDBRAKE_CLI),
        handbrake_preset_1080=get_effective(db, "handbrake_preset_1080", cfg.PRESET_1080),
        handbrake_preset_4k=get_effective(db, "handbrake_preset_4k", cfg.PRESET_4K),
        encoder_family=get_effective(db, "encoder_family", cfg.ENCODER_FAMILY),
        encoder_fallback_cpu=get_effective(db, "encoder_fallback_cpu", "true"),
        scheduler_next_run=state.scheduler.next_run(),
        webhook_username=get_effective(db, "webhook_username", ""),
        webhook_password_set=bool(get_setting(db, "webhook_password_hash")),
    )


@router.put("", response_model=dict, dependencies=[Depends(require_auth)])
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    cfg = _cfg.settings
    updated: list[str] = []

    if body.new_password is not None:
        current_hash = get_setting(db, "app_password_hash")
        if current_hash:
            if not body.current_password or not bcrypt.checkpw(
                body.current_password.encode(), current_hash.encode()
            ):
                raise HTTPException(status_code=403, detail="Wrong current password")
        else:
            expected = getattr(cfg, "APP_PASSWORD", None)
            if body.current_password != expected:
                raise HTTPException(status_code=403, detail="Wrong current password")
        new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
        set_setting(db, "app_password_hash", new_hash)
        updated.append("app_password")

    simple_fields = [
        "sonarr_url", "radarr_url", "sftp_host", "sftp_port", "sftp_username",
        "handbrake_cli", "handbrake_preset_1080", "handbrake_preset_4k",
        "encoder_family", "encoder_fallback_cpu",
        "scheduler_run_at_startup", "webhook_username",
    ]
    for field in simple_fields:
        val = getattr(body, field, None)
        if val is not None and val not in ("", _REDACTED):
            set_setting(db, field, val)
            updated.append(field)

    for field in ["sonarr_api_key", "radarr_api_key", "sftp_username", "sftp_password"]:
        val = getattr(body, field, None)
        if val and val != _REDACTED:
            set_setting(db, field, val)
            updated.append(field)

    if body.webhook_password is not None and body.webhook_password not in ("", _REDACTED):
        wh_hash = bcrypt.hashpw(body.webhook_password.encode(), bcrypt.gensalt()).decode()
        set_setting(db, "webhook_password_hash", wh_hash)
        updated.append("webhook_password")

    schedule_changed = False
    if body.scheduler_cron is not None or "scheduler_cron" in (body.model_fields_set or set()):
        cron = body.scheduler_cron
        if cron is not None and not SchedulerController.validate_cron(cron):
            raise HTTPException(status_code=400, detail="Invalid cron expression")
        set_setting(db, "scheduler_cron", cron)
        updated.append("scheduler_cron")
        schedule_changed = True
    if body.scheduler_run_at_startup is not None:
        schedule_changed = True

    db.commit()

    if schedule_changed:
        new_cron = get_setting(db, "scheduler_cron")
        state.scheduler.reschedule(new_cron)

    return {"updated": updated}


class TestBody(BaseModel):
    url: str | None = None
    api_key: str | None = None
    host: str | None = None
    port: str | None = None
    username: str | None = None
    password: str | None = None


@router.post("/test/{service}", dependencies=[Depends(require_auth)])
def test_connection(service: str, body: TestBody, db: Session = Depends(get_db)):
    """Test a connection using form values; falls back to DB for unchanged fields."""
    cfg = _cfg.settings
    if service not in ("sonarr", "radarr", "sftp"):
        raise HTTPException(status_code=400, detail="Unknown service")

    def _use(form_val: str | None, db_key: str, env_fallback: str) -> str:
        """Use the form value if it was actually changed, otherwise use DB/env."""
        if form_val and form_val != _REDACTED:
            return form_val
        return get_effective(db, db_key, env_fallback)

    try:
        if service in ("sonarr", "radarr"):
            import requests as _req
            if service == "sonarr":
                url = _use(body.url, "sonarr_url", cfg.SONARR_URL)
                key = _use(body.api_key, "sonarr_api_key", cfg.SONARR_API_KEY)
            else:
                url = _use(body.url, "radarr_url", cfg.RADARR_URL)
                key = _use(body.api_key, "radarr_api_key", cfg.RADARR_API_KEY)
            r = _req.get(
                f"{url.rstrip('/')}/api/v3/system/status",
                headers={"X-Api-Key": key},
                timeout=5,
            )
            return {"ok": r.ok, "code": r.status_code}
        else:  # sftp
            import paramiko
            host = _use(body.host, "sftp_host", cfg.SFTP_HOST)
            port = int(_use(body.port, "sftp_port", str(cfg.SFTP_PORT)))
            username = _use(body.username, "sftp_username", cfg.SFTP_USERNAME)
            password = _use(body.password, "sftp_password", cfg.SFTP_PASSWORD)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=username, password=password, timeout=5)
            client.close()
            return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
