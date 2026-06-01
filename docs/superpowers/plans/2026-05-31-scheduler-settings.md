# Scheduler & Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cron-based auto-scan scheduler and a full Settings page (Scheduler / Connections / Transcoding / Security) to the h265 transcoder.

**Architecture:** APScheduler `AsyncIOScheduler` runs inside the FastAPI lifespan, reading its cron config from the `Setting` table. A new `/api/settings` router handles GET/PUT for all editable settings. The React frontend gets a new `/settings` page with four collapsible sections and per-section Save buttons.

**Tech Stack:** Python `apscheduler>=3.10`, `bcrypt`, FastAPI, SQLAlchemy, React 18, TanStack Query 5, `cronstrue` npm package, Tailwind CSS.

---

## File Map

**Create:**
- `source_code/transcoder/scheduler.py` — SchedulerController wrapping AsyncIOScheduler
- `source_code/transcoder/api/routers/settings.py` — GET/PUT /api/settings
- `source_code/web/src/pages/Settings.tsx` — Settings page UI

**Modify:**
- `source_code/requirements.txt` — add apscheduler, bcrypt
- `source_code/transcoder/repo.py` — add get_effective(), seed_settings_from_env()
- `source_code/transcoder/api/schemas.py` — add SettingsOut, SettingsUpdate
- `source_code/transcoder/api/state.py` — add scheduler singleton
- `source_code/transcoder/api/app.py` — wire scheduler lifespan, register settings router, seed settings
- `source_code/transcoder/engine/discovery.py` — use get_effective for sonarr/radarr URL+key
- `source_code/transcoder/engine/worker.py` — use get_effective for sftp/handbrake
- `source_code/transcoder/sftp_client.py` — use get_effective for sftp host/port/user/pass
- `source_code/web/package.json` — add cronstrue
- `source_code/web/src/api/types.ts` — add Settings type
- `source_code/web/src/api/client.ts` — add getSettings(), updateSettings()
- `source_code/web/src/App.tsx` — add /settings route + nav link

---

## Task 1 — apscheduler dependency + SchedulerController

**Files:**
- Modify: `source_code/requirements.txt`
- Create: `source_code/transcoder/scheduler.py`

- [ ] **Step 1: Add dependencies to requirements.txt**

Add after the last line:
```
apscheduler>=3.10
bcrypt>=4.0
```

- [ ] **Step 2: Create scheduler.py**

```python
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("transcoder")


class SchedulerController:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._job_fn = None  # set by app.py after startup

    def set_job_fn(self, fn):
        """Register the async callable to run on schedule."""
        self._job_fn = fn

    def start(self, cron: str | None, run_at_startup: bool) -> None:
        self._scheduler.start()
        if cron:
            self._register(cron)
        if run_at_startup and self._job_fn:
            import asyncio
            asyncio.ensure_future(self._job_fn())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def reschedule(self, cron: str | None) -> None:
        self._scheduler.remove_all_jobs()
        if cron:
            self._register(cron)

    def next_run(self) -> str | None:
        job = self._scheduler.get_job("scheduled_scan")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None

    def _register(self, cron: str) -> None:
        minute, hour, day, month, dow = cron.strip().split()
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow
        )
        self._scheduler.add_job(
            self._job_fn, trigger, id="scheduled_scan", replace_existing=True
        )

    @staticmethod
    def validate_cron(cron: str) -> bool:
        try:
            parts = cron.strip().split()
            if len(parts) != 5:
                return False
            minute, hour, day, month, dow = parts
            CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)
            return True
        except Exception:
            return False
```

- [ ] **Step 3: Commit**

```bash
git add source_code/requirements.txt source_code/transcoder/scheduler.py
git commit -m "feat: add SchedulerController + apscheduler dependency"
```

---

## Task 2 — repo helpers: get_effective + seed_settings_from_env

**Files:**
- Modify: `source_code/transcoder/repo.py`

- [ ] **Step 1: Read current repo.py** and append helpers at the bottom.

- [ ] **Step 2: Add get_effective and seed_settings_from_env**

Add after the existing `set_setting` function:

```python
def get_effective(db, key: str, fallback: str) -> str:
    """Return DB setting value if present, else fallback."""
    val = get_setting(db, key)
    return val if val is not None else fallback


def seed_settings_from_env(db, mapping: dict[str, str]) -> None:
    """Write key→value into Setting table only if key is absent."""
    for key, value in mapping.items():
        if get_setting(db, key) is None and value:
            set_setting(db, key, value)
    db.commit()
```

- [ ] **Step 3: Commit**

```bash
git add source_code/transcoder/repo.py
git commit -m "feat: add get_effective and seed_settings_from_env helpers"
```

---

## Task 3 — schemas: SettingsOut + SettingsUpdate

**Files:**
- Modify: `source_code/transcoder/api/schemas.py`

- [ ] **Step 1: Read current schemas.py**, then append:

```python
class SettingsOut(BaseModel):
    scheduler_cron: str | None = None
    scheduler_run_at_startup: str = "false"
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    radarr_url: str = ""
    radarr_api_key: str = ""
    sftp_host: str = ""
    sftp_port: str = "22"
    sftp_username: str = ""
    sftp_password: str = ""
    handbrake_cli: str = ""
    handbrake_preset: str = "H.265 NVENC 1080p"
    scheduler_next_run: str | None = None


class SettingsUpdate(BaseModel):
    scheduler_cron: str | None = None
    scheduler_run_at_startup: str | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
    radarr_url: str | None = None
    radarr_api_key: str | None = None
    sftp_host: str | None = None
    sftp_port: str | None = None
    sftp_username: str | None = None
    sftp_password: str | None = None
    handbrake_cli: str | None = None
    handbrake_preset: str | None = None
    current_password: str | None = None
    new_password: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add source_code/transcoder/api/schemas.py
git commit -m "feat: add SettingsOut and SettingsUpdate schemas"
```

---

## Task 4 — settings router

**Files:**
- Create: `source_code/transcoder/api/routers/settings.py`

The REDACTED sentinel `"••••••••"` is returned for credential fields on GET.
On PUT, an empty string or the sentinel means "keep existing".

- [ ] **Step 1: Create the router**

```python
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from transcoder.api.auth import require_auth
from transcoder.api.deps import get_db
from transcoder.api import state
from transcoder.api.schemas import SettingsOut, SettingsUpdate
from transcoder.repo import get_setting, set_setting, get_effective
from transcoder.scheduler import SchedulerController
from transcoder import config as _cfg

router = APIRouter(prefix="/api/settings", tags=["settings"])

_REDACTED = "••••••••"
_CREDENTIAL_KEYS = {
    "sonarr_api_key", "radarr_api_key",
    "sftp_username", "sftp_password",
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
        sftp_username=_mask(db, "sftp_username", cfg.SFTP_USERNAME),
        sftp_password=_mask(db, "sftp_password", cfg.SFTP_PASSWORD),
        handbrake_cli=get_effective(db, "handbrake_cli", cfg.HANDBRAKE_CLI),
        handbrake_preset=get_effective(db, "handbrake_preset", cfg.HANDBRAKE_PRESET),
        scheduler_next_run=state.scheduler.next_run(),
    )


@router.put("", response_model=dict, dependencies=[Depends(require_auth)])
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    cfg = _cfg.settings
    updated: list[str] = []

    # --- password change ---
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

    # --- scalar fields ---
    simple_fields = [
        "sonarr_url", "radarr_url", "sftp_host", "sftp_port",
        "handbrake_cli", "handbrake_preset",
        "scheduler_run_at_startup",
    ]
    for field in simple_fields:
        val = getattr(body, field, None)
        if val is not None and val not in ("", _REDACTED):
            set_setting(db, field, val)
            updated.append(field)

    # --- credentials (skip redacted / empty) ---
    for field in ["sonarr_api_key", "radarr_api_key", "sftp_username", "sftp_password"]:
        val = getattr(body, field, None)
        if val and val != _REDACTED:
            set_setting(db, field, val)
            updated.append(field)

    # --- cron ---
    schedule_changed = False
    if "scheduler_cron" in (body.model_fields_set or set()):
        cron = body.scheduler_cron
        if cron is not None and not SchedulerController.validate_cron(cron):
            raise HTTPException(status_code=400, detail="Invalid cron expression")
        set_setting(db, "scheduler_cron", cron)
        updated.append("scheduler_cron")
        schedule_changed = True
    if "scheduler_run_at_startup" in (body.model_fields_set or set()):
        schedule_changed = True

    db.commit()

    if schedule_changed:
        new_cron = get_setting(db, "scheduler_cron")
        state.scheduler.reschedule(new_cron)

    return {"updated": updated}
```

- [ ] **Step 2: Commit**

```bash
git add source_code/transcoder/api/routers/settings.py
git commit -m "feat: add /api/settings GET+PUT router"
```

---

## Task 5 — wire state.py + app.py

**Files:**
- Modify: `source_code/transcoder/api/state.py`
- Modify: `source_code/transcoder/api/app.py`

- [ ] **Step 1: Add scheduler singleton to state.py**

Read state.py. After the existing singleton instantiations, append:

```python
from transcoder.scheduler import SchedulerController
scheduler: SchedulerController = SchedulerController()
```

- [ ] **Step 2: Update app.py lifespan**

Read app.py. In the lifespan startup block, after `state.controller.start()`, add:

```python
# seed settings from env on first startup
from transcoder.repo import seed_settings_from_env, get_setting
import bcrypt
cfg = settings  # already imported as 'from transcoder.config import settings'
with state.SessionLocal() as _db:
    seed_settings_from_env(_db, {
        "sonarr_url": cfg.SONARR_URL,
        "sonarr_api_key": cfg.SONARR_API_KEY,
        "radarr_url": cfg.RADARR_URL,
        "radarr_api_key": cfg.RADARR_API_KEY,
        "sftp_host": cfg.SFTP_HOST,
        "sftp_port": str(cfg.SFTP_PORT),
        "sftp_username": cfg.SFTP_USERNAME,
        "sftp_password": cfg.SFTP_PASSWORD,
        "handbrake_cli": cfg.HANDBRAKE_CLI,
        "handbrake_preset": cfg.HANDBRAKE_PRESET,
    })
    # seed bcrypt hash for app_password if not set
    if get_setting(_db, "app_password_hash") is None and cfg.APP_PASSWORD:
        import bcrypt as _bcrypt
        _hash = _bcrypt.hashpw(cfg.APP_PASSWORD.encode(), _bcrypt.gensalt()).decode()
        from transcoder.repo import set_setting
        set_setting(_db, "app_password_hash", _hash)
        _db.commit()
    # start scheduler
    from transcoder.repo import get_setting as _gs
    _cron = _gs(_db, "scheduler_cron")
    _startup = _gs(_db, "scheduler_run_at_startup") == "true"

# define scheduled job fn (calls same logic as POST /run)
async def _scheduled_run():
    from transcoder.db import SessionLocal as SL
    from transcoder.api.routers.scan import _run_full
    async with SL() as _db2:
        await _run_full(app="all", scope="new", db=_db2,
                        sonarr=state.sonarr, radarr=state.radarr,
                        controller=state.controller)

state.scheduler.set_job_fn(_scheduled_run)
state.scheduler.start(_cron, _startup)
```

In the lifespan shutdown block, before `state.controller.shutdown()`, add:

```python
state.scheduler.shutdown()
```

- [ ] **Step 3: Register settings router in app.py**

Find where other routers are included (e.g. `app.include_router(scan.router)`) and add:

```python
from transcoder.api.routers import settings as settings_router
app.include_router(settings_router.router)
```

- [ ] **Step 4: Update auth.py password check to prefer DB hash**

Read auth.py. In the login endpoint, replace the plain-text password comparison with:

```python
from transcoder.repo import get_setting
from transcoder.api.deps import get_db  # or use SessionLocal directly

# inside the login route, before checking APP_PASSWORD:
with SessionLocal() as db:
    stored_hash = get_setting(db, "app_password_hash")

if stored_hash:
    import bcrypt
    if not bcrypt.checkpw(password.encode(), stored_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid password")
else:
    if password != settings.APP_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")
```

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/api/state.py source_code/transcoder/api/app.py source_code/transcoder/api/auth.py
git commit -m "feat: wire SchedulerController into FastAPI lifespan; seed settings from env"
```

---

## Task 6 — callsite updates (discovery, worker, sftp_client)

**Files:**
- Modify: `source_code/transcoder/engine/discovery.py`
- Modify: `source_code/transcoder/engine/worker.py`
- Modify: `source_code/transcoder/sftp_client.py`

Read each file. Replace direct `settings.X` references for the seeded keys with `get_effective(db, "x", settings.X)`. The `db` session must already be available in scope for these functions.

- [ ] **Step 1: Update discovery.py**

At the top, add:
```python
from transcoder.repo import get_effective
```

Replace uses of `settings.SONARR_URL`, `settings.SONARR_API_KEY`, `settings.RADARR_URL`, `settings.RADARR_API_KEY` with `get_effective(db, "sonarr_url", settings.SONARR_URL)` etc. The `db` session is already passed into discover functions.

- [ ] **Step 2: Update worker.py**

At the top add:
```python
from transcoder.repo import get_effective
```

Replace `settings.HANDBRAKE_CLI` with `get_effective(db, "handbrake_cli", settings.HANDBRAKE_CLI)` and `settings.HANDBRAKE_PRESET` with `get_effective(db, "handbrake_preset", settings.HANDBRAKE_PRESET)`. Use the `db` session already in scope.

- [ ] **Step 3: Update sftp_client.py**

If sftp_client.py creates connections using config values directly, update them to accept override parameters or read from DB. Simplest: accept keyword overrides in the constructor/connect method:

```python
def __init__(self, host=None, port=None, username=None, password=None):
    cfg = settings
    self.host = host or cfg.SFTP_HOST
    self.port = port or cfg.SFTP_PORT
    self.username = username or cfg.SFTP_USERNAME
    self.password = password or cfg.SFTP_PASSWORD
```

In worker.py, when instantiating SftpClient, read effective values from DB:
```python
sftp = SftpClient(
    host=get_effective(db, "sftp_host", settings.SFTP_HOST),
    port=int(get_effective(db, "sftp_port", str(settings.SFTP_PORT))),
    username=get_effective(db, "sftp_username", settings.SFTP_USERNAME),
    password=get_effective(db, "sftp_password", settings.SFTP_PASSWORD),
)
```

- [ ] **Step 4: Commit**

```bash
git add source_code/transcoder/engine/discovery.py source_code/transcoder/engine/worker.py source_code/transcoder/sftp_client.py
git commit -m "feat: use get_effective for all runtime config; supports DB overrides"
```

---

## Task 7 — frontend API layer (types + client + cronstrue)

**Files:**
- Modify: `source_code/web/package.json`
- Modify: `source_code/web/src/api/types.ts`
- Modify: `source_code/web/src/api/client.ts`

- [ ] **Step 1: Install cronstrue**

```bash
cd source_code/web && npm install cronstrue
```

- [ ] **Step 2: Add Settings type to types.ts**

Append to types.ts:
```typescript
export interface Settings {
  scheduler_cron: string | null;
  scheduler_run_at_startup: string;
  sonarr_url: string;
  sonarr_api_key: string;
  radarr_url: string;
  radarr_api_key: string;
  sftp_host: string;
  sftp_port: string;
  sftp_username: string;
  sftp_password: string;
  handbrake_cli: string;
  handbrake_preset: string;
  scheduler_next_run: string | null;
}

export interface SettingsUpdate {
  scheduler_cron?: string | null;
  scheduler_run_at_startup?: string;
  sonarr_url?: string;
  sonarr_api_key?: string;
  radarr_url?: string;
  radarr_api_key?: string;
  sftp_host?: string;
  sftp_port?: string;
  sftp_username?: string;
  sftp_password?: string;
  handbrake_cli?: string;
  handbrake_preset?: string;
  current_password?: string;
  new_password?: string;
}
```

- [ ] **Step 3: Add API functions to client.ts**

Append to client.ts:
```typescript
export const getSettings = (): Promise<Settings> =>
  api.get<Settings>('/api/settings');

export const updateSettings = (payload: SettingsUpdate): Promise<{ updated: string[] }> =>
  api.put<{ updated: string[] }>('/api/settings', payload);
```

(Add `put` to the `api` object if missing: `put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) })`)

- [ ] **Step 4: Commit**

```bash
cd source_code/web && npm install
git add source_code/web/package.json source_code/web/package-lock.json source_code/web/src/api/types.ts source_code/web/src/api/client.ts
git commit -m "feat: add Settings types and API client functions; add cronstrue"
```

---

## Task 8 — Settings.tsx page

**Files:**
- Create: `source_code/web/src/pages/Settings.tsx`

Read an existing page (e.g. Jobs.tsx) for pattern reference before writing.

- [ ] **Step 1: Create Settings.tsx**

```tsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import cronstrue from 'cronstrue';
import { getSettings, updateSettings } from '../api/client';
import type { SettingsUpdate } from '../api/types';

const REDACTED = '••••••••';
const PRESETS = ['H.265 NVENC 1080p', 'H.265 NVENC 2160p 4K'];

function Section({ title, children, onSave, saving, saved, error }: {
  title: string;
  children: React.ReactNode;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  error: string | null;
}) {
  return (
    <div className="mb-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="mb-4 text-lg font-semibold text-gray-900">{title}</h2>
      <div className="space-y-4">{children}</div>
      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-sm text-green-600">Saved</span>}
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 items-start gap-4">
      <label className="pt-2 text-sm font-medium text-gray-700">{label}</label>
      <div className="col-span-2">{children}</div>
    </div>
  );
}

function Input({ value, onChange, type = 'text', placeholder }: {
  value: string; onChange: (v: string) => void; type?: string; placeholder?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
    />
  );
}

function MaskedInput({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="flex gap-2">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        className="shrink-0 rounded border border-gray-300 px-3 py-2 text-xs text-gray-600 hover:bg-gray-50"
      >
        {show ? 'Hide' : 'Show'}
      </button>
    </div>
  );
}

function cronDescription(expr: string): string {
  try { return cronstrue.toString(expr); }
  catch { return 'Invalid cron expression'; }
}

export default function Settings() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings });

  // --- Scheduler state ---
  const [cron, setCron] = useState('');
  const [schedEnabled, setSchedEnabled] = useState(false);
  const [runAtStartup, setRunAtStartup] = useState(false);
  const [schedSaved, setSchedSaved] = useState(false);
  const [schedError, setSchedError] = useState<string | null>(null);

  // --- Connections state ---
  const [sonarrUrl, setSonarrUrl] = useState('');
  const [sonarrKey, setSonarrKey] = useState(REDACTED);
  const [radarrUrl, setRadarrUrl] = useState('');
  const [radarrKey, setRadarrKey] = useState(REDACTED);
  const [sftpHost, setSftpHost] = useState('');
  const [sftpPort, setSftpPort] = useState('22');
  const [sftpUser, setSftpUser] = useState(REDACTED);
  const [sftpPass, setSftpPass] = useState(REDACTED);
  const [connSaved, setConnSaved] = useState(false);
  const [connError, setConnError] = useState<string | null>(null);

  // --- Transcoding state ---
  const [hbCli, setHbCli] = useState('');
  const [hbPreset, setHbPreset] = useState(PRESETS[0]);
  const [transSaved, setTransSaved] = useState(false);
  const [transError, setTransError] = useState<string | null>(null);

  // --- Security state ---
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [secSaved, setSecSaved] = useState(false);
  const [secError, setSecError] = useState<string | null>(null);

  // Seed local state from fetched data once
  const [seeded, setSeeded] = useState(false);
  if (data && !seeded) {
    setCron(data.scheduler_cron ?? '');
    setSchedEnabled(!!data.scheduler_cron);
    setRunAtStartup(data.scheduler_run_at_startup === 'true');
    setSonarrUrl(data.sonarr_url);
    setSonarrKey(data.sonarr_api_key || REDACTED);
    setRadarrUrl(data.radarr_url);
    setRadarrKey(data.radarr_api_key || REDACTED);
    setSftpHost(data.sftp_host);
    setSftpPort(data.sftp_port);
    setSftpUser(data.sftp_username || REDACTED);
    setSftpPass(data.sftp_password || REDACTED);
    setHbCli(data.handbrake_cli);
    setHbPreset(data.handbrake_preset || PRESETS[0]);
    setSeeded(true);
  }

  const mut = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  });

  const save = async (
    payload: SettingsUpdate,
    setSaved: (v: boolean) => void,
    setError: (v: string | null) => void
  ) => {
    setError(null);
    try {
      await mut.mutateAsync(payload);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setSaved(false);
      setError(e instanceof Error ? e.message : 'Save failed');
    }
  };

  if (isLoading) return <div className="p-8 text-gray-500">Loading settings…</div>;

  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-2xl font-bold text-gray-900">Settings</h1>

      {/* Scheduler */}
      <Section
        title="Scheduler"
        onSave={() => save(
          {
            scheduler_cron: schedEnabled ? cron : null,
            scheduler_run_at_startup: runAtStartup ? 'true' : 'false',
          },
          setSchedSaved, setSchedError
        )}
        saving={mut.isPending}
        saved={schedSaved}
        error={schedError}
      >
        <Field label="Run at startup">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={runAtStartup}
              onChange={e => setRunAtStartup(e.target.checked)}
              className="h-4 w-4"
            />
            Trigger a scan when the server starts
          </label>
        </Field>
        <Field label="Enable schedule">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={schedEnabled}
              onChange={e => setSchedEnabled(e.target.checked)}
              className="h-4 w-4"
            />
            Run on a cron schedule
          </label>
        </Field>
        {schedEnabled && (
          <Field label="Cron expression">
            <Input value={cron} onChange={setCron} placeholder="0 3 * * *" />
            {cron && (
              <p className="mt-1 text-xs text-gray-500">{cronDescription(cron)}</p>
            )}
            {data?.scheduler_next_run && (
              <p className="mt-1 text-xs text-gray-400">
                Next run: {new Date(data.scheduler_next_run).toLocaleString()}
              </p>
            )}
            <a
              href="https://crontab.guru"
              target="_blank"
              rel="noreferrer"
              className="mt-1 block text-xs text-blue-500 hover:underline"
            >
              crontab.guru →
            </a>
          </Field>
        )}
      </Section>

      {/* Connections */}
      <Section
        title="Connections"
        onSave={() => save(
          { sonarr_url: sonarrUrl, sonarr_api_key: sonarrKey,
            radarr_url: radarrUrl, radarr_api_key: radarrKey,
            sftp_host: sftpHost, sftp_port: sftpPort,
            sftp_username: sftpUser, sftp_password: sftpPass },
          setConnSaved, setConnError
        )}
        saving={mut.isPending}
        saved={connSaved}
        error={connError}
      >
        <Field label="Sonarr URL"><Input value={sonarrUrl} onChange={setSonarrUrl} /></Field>
        <Field label="Sonarr API key"><MaskedInput value={sonarrKey} onChange={setSonarrKey} /></Field>
        <Field label="Radarr URL"><Input value={radarrUrl} onChange={setRadarrUrl} /></Field>
        <Field label="Radarr API key"><MaskedInput value={radarrKey} onChange={setRadarrKey} /></Field>
        <Field label="SFTP host"><Input value={sftpHost} onChange={setSftpHost} /></Field>
        <Field label="SFTP port"><Input value={sftpPort} onChange={setSftpPort} /></Field>
        <Field label="SFTP username"><MaskedInput value={sftpUser} onChange={setSftpUser} /></Field>
        <Field label="SFTP password"><MaskedInput value={sftpPass} onChange={setSftpPass} /></Field>
      </Section>

      {/* Transcoding */}
      <Section
        title="Transcoding"
        onSave={() => save(
          { handbrake_cli: hbCli, handbrake_preset: hbPreset },
          setTransSaved, setTransError
        )}
        saving={mut.isPending}
        saved={transSaved}
        error={transError}
      >
        <Field label="HandBrake CLI path">
          <Input value={hbCli} onChange={setHbCli} placeholder="C:\...\HandBrakeCLI.exe" />
        </Field>
        <Field label="Preset">
          <select
            value={hbPreset}
            onChange={e => setHbPreset(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </Field>
      </Section>

      {/* Security */}
      <Section
        title="Security"
        onSave={() => {
          if (newPw !== confirmPw) { setSecError('Passwords do not match'); return; }
          save(
            { current_password: currentPw, new_password: newPw },
            setSecSaved, setSecError
          );
        }}
        saving={mut.isPending}
        saved={secSaved}
        error={secError}
      >
        <Field label="Current password">
          <Input type="password" value={currentPw} onChange={setCurrentPw} />
        </Field>
        <Field label="New password">
          <Input type="password" value={newPw} onChange={setNewPw} />
        </Field>
        <Field label="Confirm new password">
          <Input type="password" value={confirmPw} onChange={setConfirmPw} />
        </Field>
      </Section>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add source_code/web/src/pages/Settings.tsx
git commit -m "feat: add Settings page with Scheduler/Connections/Transcoding/Security sections"
```

---

## Task 9 — routing + nav

**Files:**
- Modify: `source_code/web/src/App.tsx`

- [ ] **Step 1: Read App.tsx**, then add the Settings route.

In the route list alongside existing routes, add:
```tsx
import Settings from './pages/Settings';
// ...
<Route path="/settings" element={<Settings />} />
```

In the Nav component (same file or Nav.tsx), add a link:
```tsx
<NavLink to="/settings">Settings</NavLink>
```

- [ ] **Step 2: Commit**

```bash
git add source_code/web/src/App.tsx
git commit -m "feat: add /settings route and nav link"
```

---

## Task 10 — smoke test

- [ ] **Step 1: Install backend deps**

```bash
cd source_code && pip install -r requirements.txt
```

- [ ] **Step 2: Start the server**

```bash
cd source_code && python -m transcoder.api
```

Expected: server starts, no import errors, scheduler initialises (check log/api.log).

- [ ] **Step 3: Build frontend**

```bash
cd source_code/web && npm install && npm run build
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 4: Verify settings endpoint**

```bash
curl -c cookies.txt -X POST http://localhost:8765/api/login -H "Content-Type: application/json" -d "{\"password\":\"<your_password>\"}"
curl -b cookies.txt http://localhost:8765/api/settings
```

Expected: JSON with all settings fields, credentials shown as `••••••••`.

- [ ] **Step 5: Navigate to /settings in browser**

Open http://localhost:8765/settings — all four sections visible, cron helper renders human-readable text.

- [ ] **Step 6: Final commit (if any loose files)**

```bash
git add -u && git commit -m "chore: scheduler + settings page complete"
```
