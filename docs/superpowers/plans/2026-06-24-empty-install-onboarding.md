# Empty-Install Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a freshly installed, unconfigured instance boot and walk the user through a guided first-run setup (password required; connections + HandBrake path skippable).

**Architecture:** Make `config.py`'s connection/credential fields optional so the app stops crashing at import; resolve `SECRET_KEY` from env-or-generated-file; expose `needs_setup` on `/api/me` and add an open-once `POST /api/setup/password`; gate a new React `<Setup>` wizard in `AuthGate`.

**Tech Stack:** Python 3.10+, FastAPI, pydantic-settings, SQLAlchemy, bcrypt; React + TypeScript + Vite, TanStack Query, Vitest.

## Global Constraints

- TDD: write the failing test first, watch it fail, then implement. (CLAUDE.md)
- Backend tests: `python -m pytest` from repo root (`pythonpath = solution`).
- Frontend tests: `cd solution/web && npm test` (runs `tsc -b` then Vitest).
- Windows shell is PowerShell; commit messages via `git commit -F <file>` (no PS here-strings).
- Connection/credential values are read via `get_effective(db, key, settings.X)`; DB value wins, env is fallback. Do not change that contract.
- `seed_settings_from_env` already skips empty values — empty config defaults must never seed or clobber DB rows.
- Backward compatibility: an install with a populated `.env` and/or an existing `app_password_hash` must see no wizard and identical behavior.

---

### Task 1: Make connection/credential config fields optional

**Files:**
- Modify: `solution/transcoder/config.py:12-21`
- Test: `tests/test_config_optional.py` (create)

**Interfaces:**
- Produces: `transcoder.config.Settings` instantiable with no env; fields
  `SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY, SFTP_HOST,
  SFTP_USERNAME, SFTP_PASSWORD, HANDBRAKE_CLI, APP_PASSWORD, SECRET_KEY`
  all default to `""` (type `str`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_optional.py`:

```python
"""A fresh install has no .env (gitignored), so Settings must load with the
connection/credential fields defaulting to "" instead of raising
ValidationError and crashing the app at import."""

REQUIRED_NOW_OPTIONAL = [
    "SONARR_URL", "SONARR_API_KEY", "RADARR_URL", "RADARR_API_KEY",
    "SFTP_HOST", "SFTP_USERNAME", "SFTP_PASSWORD", "HANDBRAKE_CLI",
    "APP_PASSWORD", "SECRET_KEY",
]


def test_settings_loads_with_no_env(monkeypatch):
    # tests/conftest.py sets these in os.environ; remove them so we exercise the
    # true empty-install path.
    for key in REQUIRED_NOW_OPTIONAL:
        monkeypatch.delenv(key, raising=False)
    from transcoder.config import Settings
    s = Settings(_env_file=None)
    for key in REQUIRED_NOW_OPTIONAL:
        assert getattr(s, key) == "", key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_optional.py -q`
Expected: FAIL — `ValidationError` (fields required) raised by `Settings(_env_file=None)`.

- [ ] **Step 3: Implement — give the fields `""` defaults**

In `solution/transcoder/config.py`, replace the required block (lines 12-21):

```python
    # --- Connections / secrets: optional so an unconfigured install still boots.
    # Values are configured at runtime via the setup wizard / Settings page and
    # read through get_effective(db, key, settings.X); env is only a fallback.
    # SFTP_* are prefixed to avoid collision with Windows USERNAME/HOSTNAME.
    SONARR_URL: str = ""
    SONARR_API_KEY: str = ""
    RADARR_URL: str = ""
    RADARR_API_KEY: str = ""
    SFTP_HOST: str = ""
    SFTP_USERNAME: str = ""
    SFTP_PASSWORD: str = ""
    HANDBRAKE_CLI: str = ""
    APP_PASSWORD: str = ""
    SECRET_KEY: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_optional.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `python -m pytest -q`
Expected: all pass (existing tests still set env via `tests/conftest.py`).

- [ ] **Step 6: Commit**

```bash
git add solution/transcoder/config.py tests/test_config_optional.py
git commit -F <msgfile>   # "fix(config): make connection/credential fields optional so empty installs boot"
```

---

### Task 2: Resolve SECRET_KEY from env or a generated file

**Files:**
- Modify: `solution/transcoder/config.py` (add `resolve_secret_key()` at end of file)
- Modify: `solution/transcoder/api/app.py:96`
- Test: `tests/test_secret_key.py` (create)

**Interfaces:**
- Consumes: `settings.SECRET_KEY` (Task 1), `settings.DATABASE_URL`,
  `transcoder.backup.db_path_from_url(url) -> str`.
- Produces: `transcoder.config.resolve_secret_key() -> str` — non-empty; env
  value if set, else read/generate a `secret_key` file beside the DB.

- [ ] **Step 1: Write the failing test**

Create `tests/test_secret_key.py`:

```python
"""SECRET_KEY signs session cookies and cannot be empty. On an empty install it
must be generated once and reused across restarts, persisted to a file beside
the database (the SessionMiddleware is added before init_db runs, so the DB is
not available yet)."""


def test_prefers_env_secret_when_set(monkeypatch):
    from transcoder import config
    monkeypatch.setattr(config.settings, "SECRET_KEY", "env-secret-value")
    assert config.resolve_secret_key() == "env-secret-value"


def test_generates_and_reuses_file_when_env_empty(monkeypatch, tmp_path):
    from transcoder import config
    monkeypatch.setattr(config.settings, "SECRET_KEY", "")
    db = tmp_path / "transcoder.db"
    monkeypatch.setattr(config.settings, "DATABASE_URL", f"sqlite:///{db.as_posix()}")

    first = config.resolve_secret_key()
    assert first  # non-empty
    assert (tmp_path / "secret_key").exists()

    second = config.resolve_secret_key()
    assert second == first  # reused, not regenerated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_secret_key.py -q`
Expected: FAIL — `AttributeError: module 'transcoder.config' has no attribute 'resolve_secret_key'`.

- [ ] **Step 3: Implement `resolve_secret_key`**

Append to `solution/transcoder/config.py` (after `settings = Settings()`):

```python
def resolve_secret_key() -> str:
    """Session-signing key. Prefer an explicit env SECRET_KEY; otherwise read a
    `secret_key` file next to the database, generating and persisting one on
    first run so sessions survive restarts. Kept out of the DB because the
    SessionMiddleware is wired up before init_db() runs."""
    import os
    import secrets
    from pathlib import Path

    if settings.SECRET_KEY:
        return settings.SECRET_KEY

    from transcoder.backup import db_path_from_url  # lazy: avoid import cycle
    db_path = db_path_from_url(settings.DATABASE_URL)
    key_file = Path(os.path.dirname(os.path.abspath(db_path)) or ".") / "secret_key"
    if key_file.exists():
        existing = key_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    generated = secrets.token_urlsafe(48)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(generated, encoding="utf-8")
    return generated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_secret_key.py -q`
Expected: PASS.

- [ ] **Step 5: Wire it into the app**

In `solution/transcoder/api/app.py`, update the import (line 14 area) and the middleware (line 96).

Change the config import line:

```python
from transcoder.config import settings, resolve_secret_key
```

Change the middleware line:

```python
    app.add_middleware(SessionMiddleware, secret_key=resolve_secret_key(), same_site="lax")
```

- [ ] **Step 6: Run the API suite (no regressions)**

Run: `python -m pytest tests/test_api_auth.py tests/test_api_protected.py -q`
Expected: PASS (env `SECRET_KEY=test-secret-key` is set by conftest, so the env branch is taken).

- [ ] **Step 7: Commit**

```bash
git add solution/transcoder/config.py solution/transcoder/api/app.py tests/test_secret_key.py
git commit -F <msgfile>   # "feat(config): resolve SECRET_KEY from env or a generated file"
```

---

### Task 3: `needs_setup` on /api/me + open `POST /api/setup/password`

**Files:**
- Modify: `solution/transcoder/api/auth.py`
- Test: `tests/test_api_setup.py` (create)

**Interfaces:**
- Consumes: `get_setting`, `set_setting` from `transcoder.repo`; `settings.APP_PASSWORD`;
  the `api` fixture from `tests/api_conftest.py` (yields `(client, Session)`).
- Produces:
  - `GET /api/me` → `{"authed": bool, "needs_setup": bool}`.
  - `POST /api/setup/password` body `{"password": str}` → `{"ok": true}` (200),
    sets `app_password_hash` and authes the session; `409` if a password already
    exists; `422` if blank.
  - Helper `transcoder.api.auth._password_configured(db) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_setup.py`:

```python
"""First-run setup: an empty install reports needs_setup and can set the initial
password via an open endpoint that becomes inert once a password exists."""
import transcoder.api.auth as auth
from transcoder.models import Setting


def _make_empty(api, monkeypatch):
    """Put the in-memory DB into the 'no password configured' state."""
    client, Session = api
    monkeypatch.setattr(auth.settings, "APP_PASSWORD", "")
    with Session() as db:
        db.query(Setting).filter(Setting.key == "app_password_hash").delete()
        db.commit()
    return client, Session


def test_me_reports_needs_setup_when_no_password(api, monkeypatch):
    client, _ = _make_empty(api, monkeypatch)
    body = client.get("/api/me").json()
    assert body["needs_setup"] is True


def test_me_no_setup_when_password_hash_exists(api):
    # Default fixture seeds app_password_hash (APP_PASSWORD="test-pass").
    client, _ = api
    assert client.get("/api/me").json()["needs_setup"] is False


def test_setup_password_sets_hash_and_authes(api, monkeypatch):
    client, Session = _make_empty(api, monkeypatch)
    r = client.post("/api/setup/password", json={"password": "hunter2"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # Session is now authed and setup is complete.
    me = client.get("/api/me").json()
    assert me["authed"] is True and me["needs_setup"] is False
    # Hash persisted.
    with Session() as db:
        assert db.get(Setting, "app_password_hash") is not None


def test_setup_password_conflicts_when_already_configured(api):
    client, _ = api  # default fixture already has a password hash
    r = client.post("/api/setup/password", json={"password": "whatever"})
    assert r.status_code == 409


def test_setup_password_rejects_blank(api, monkeypatch):
    client, _ = _make_empty(api, monkeypatch)
    r = client.post("/api/setup/password", json={"password": "   "})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api_setup.py -q`
Expected: FAIL — `/api/me` has no `needs_setup` key (KeyError) and `/api/setup/password` returns 404.

- [ ] **Step 3: Implement in `auth.py`**

In `solution/transcoder/api/auth.py`, update imports and add the helper, the
`/me` field, and the new endpoint.

Update the repo import line:

```python
from transcoder.repo import get_setting, set_setting
```

Add bcrypt-based helper + endpoint (the `me` route is replaced):

```python
def _password_configured(db) -> bool:
    """True once a login password exists — a stored hash or a non-empty env
    APP_PASSWORD. Drives first-run detection."""
    return get_setting(db, "app_password_hash") is not None or bool(settings.APP_PASSWORD)


@router.get("/me")
def me(request: Request):
    with SessionLocal() as db:
        configured = _password_configured(db)
    return {"authed": bool(request.session.get("authed")), "needs_setup": not configured}


class SetupPasswordIn(BaseModel):
    password: str


@router.post("/setup/password")
def setup_password(body: SetupPasswordIn, request: Request):
    """Set the initial dashboard password on a fresh install. Open (no auth)
    but allowed ONLY while no password exists, so it can't hijack a configured
    instance. On success, log the caller in."""
    if not body.password.strip():
        raise HTTPException(status_code=422, detail="Password required")
    with SessionLocal() as db:
        if _password_configured(db):
            raise HTTPException(status_code=409, detail="Already configured")
        new_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        set_setting(db, "app_password_hash", new_hash)
        db.commit()
    request.session["authed"] = True
    return {"ok": True}
```

Delete the old `me` function (lines 43-45) so only the new one remains.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_setup.py -q`
Expected: PASS (all 5).

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add solution/transcoder/api/auth.py tests/test_api_setup.py
git commit -F <msgfile>   # "feat(api): needs_setup flag + open-once /api/setup/password"
```

---

### Task 4: Frontend — surface `needs_setup` and gate the wizard

**Files:**
- Modify: `solution/web/src/auth/useMe.ts`
- Modify: `solution/web/src/auth/AuthGate.tsx`
- Modify: `solution/web/src/auth/AuthGate.test.tsx`
- Create: `solution/web/src/pages/Setup.tsx` (minimal placeholder this task; full wizard in Task 5)

**Interfaces:**
- Consumes: `GET /api/me` → `{ authed: boolean; needs_setup?: boolean }`.
- Produces: `Setup` default export — `function Setup({ onDone }: { onDone: () => void })`.
  AuthGate renders `<Setup onDone={refetch} />` when `data.needs_setup` is true.

- [ ] **Step 1: Write the failing test**

In `solution/web/src/auth/AuthGate.test.tsx`, add:

```tsx
test("shows setup wizard when needs_setup", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ authed: false, needs_setup: true }), { status: 200 })));
  wrap(<AuthGate><div>SECRET CONTENT</div></AuthGate>);
  expect(await screen.findByRole("heading", { name: /set up/i })).toBeInTheDocument();
  expect(screen.queryByText("SECRET CONTENT")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd solution/web && npm test -- AuthGate`
Expected: FAIL — no "Set up" heading (AuthGate doesn't render Setup yet) / `Setup` module missing.

- [ ] **Step 3: Update the `useMe` type**

In `solution/web/src/auth/useMe.ts`, widen the response type:

```ts
    queryFn: () => api.get<{ authed: boolean; needs_setup?: boolean }>("/api/me"),
```

- [ ] **Step 4: Create a minimal `Setup` page**

Create `solution/web/src/pages/Setup.tsx`:

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

interface SetupProps {
  onDone: () => void;
}

export default function Setup({ onDone: _onDone }: SetupProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Set up H.265 Transcoder</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted">Let's get you configured.</p>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 5: Gate the wizard in `AuthGate`**

In `solution/web/src/auth/AuthGate.tsx`, add the import and the branch (before the authed check):

```tsx
import Setup from "../pages/Setup";
```

```tsx
  if (data?.needs_setup) {
    return <Setup onDone={() => refetch()} />;
  }

  if (!data?.authed) {
    return <Login onSuccess={() => refetch()} />;
  }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd solution/web && npm test -- AuthGate`
Expected: PASS (all AuthGate tests, including the new one).

- [ ] **Step 7: Commit**

```bash
git add solution/web/src/auth/useMe.ts solution/web/src/auth/AuthGate.tsx solution/web/src/auth/AuthGate.test.tsx solution/web/src/pages/Setup.tsx
git commit -F <msgfile>   # "feat(web): gate first-run Setup wizard on needs_setup"
```

---

### Task 5: Frontend — build out the Setup wizard

**Files:**
- Modify: `solution/web/src/pages/Setup.tsx`
- Create: `solution/web/src/pages/Setup.test.tsx`

**Interfaces:**
- Consumes: `api.post("/api/setup/password", { password })`;
  `updateSettings(payload: SettingsUpdate)` from `../api/client` (PUT `/api/settings`);
  ui primitives `Button`, `Card*`, `Input`.
- Produces: a 4-step wizard. Password step required; connection + HandBrake steps
  each have **Skip** and **Save & continue**; final step calls `onDone()`.

- [ ] **Step 1: Write the failing tests**

Create `solution/web/src/pages/Setup.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import Setup from "./Setup";

afterEach(() => vi.restoreAllMocks());

test("password step posts and advances to connections", async () => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  render(<Setup onDone={() => {}} />);
  await userEvent.type(screen.getByLabelText(/password/i), "hunter2");
  await userEvent.click(screen.getByRole("button", { name: /create password/i }));

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith("/api/setup/password", expect.objectContaining({ method: "POST" })));
  // Advanced to the connections step.
  expect(await screen.findByText(/sonarr/i)).toBeInTheDocument();
});

test("can skip optional steps to finish", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ ok: true }), { status: 200 })));
  const onDone = vi.fn();

  render(<Setup onDone={onDone} />);
  await userEvent.type(screen.getByLabelText(/password/i), "hunter2");
  await userEvent.click(screen.getByRole("button", { name: /create password/i }));

  // Skip connections, then skip HandBrake, then finish.
  await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
  await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
  await userEvent.click(await screen.findByRole("button", { name: /finish|go to dashboard/i }));

  await waitFor(() => expect(onDone).toHaveBeenCalled());
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd solution/web && npm test -- Setup`
Expected: FAIL — placeholder Setup has no password field / step buttons.

- [ ] **Step 3: Implement the wizard**

Replace `solution/web/src/pages/Setup.tsx` with:

```tsx
import { useState } from "react";
import { api, ApiError } from "../api/client";
import { updateSettings } from "../api/client";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";

interface SetupProps {
  onDone: () => void;
}

type Step = "password" | "connections" | "handbrake" | "done";

export default function Setup({ onDone }: SetupProps) {
  const [step, setStep] = useState<Step>("password");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // connection fields
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrKey, setSonarrKey] = useState("");
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrKey, setRadarrKey] = useState("");
  const [sftpHost, setSftpHost] = useState("");
  const [sftpUser, setSftpUser] = useState("");
  const [sftpPass, setSftpPass] = useState("");
  const [handbrake, setHandbrake] = useState("");

  async function createPassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/api/setup/password", { password });
      setStep("connections");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not set password");
    } finally {
      setBusy(false);
    }
  }

  async function saveConnections() {
    setBusy(true);
    try {
      await updateSettings({
        sonarr_url: sonarrUrl, sonarr_api_key: sonarrKey,
        radarr_url: radarrUrl, radarr_api_key: radarrKey,
        sftp_host: sftpHost, sftp_username: sftpUser, sftp_password: sftpPass,
      });
    } finally {
      setBusy(false);
      setStep("handbrake");
    }
  }

  async function saveHandbrake() {
    setBusy(true);
    try {
      await updateSettings({ handbrake_cli: handbrake });
    } finally {
      setBusy(false);
      setStep("done");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Set up H.265 Transcoder</CardTitle>
        </CardHeader>
        <CardContent>
          {step === "password" && (
            <form onSubmit={createPassword} className="flex flex-col gap-4">
              <p className="text-sm text-muted">Choose a password for the dashboard.</p>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="setup-password" className="text-sm text-muted">Password</label>
                <Input id="setup-password" type="password" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password" required />
              </div>
              {error && <p className="text-sm text-state-failed">{error}</p>}
              <Button type="submit" disabled={busy || !password.trim()}>
                {busy ? "Saving…" : "Create password"}
              </Button>
            </form>
          )}

          {step === "connections" && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted">Connect Sonarr, Radarr, and SFTP (optional — you can do this later in Settings).</p>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">Sonarr</legend>
                <Input placeholder="Sonarr URL" value={sonarrUrl} onChange={(e) => setSonarrUrl(e.target.value)} />
                <Input placeholder="Sonarr API key" value={sonarrKey} onChange={(e) => setSonarrKey(e.target.value)} />
              </fieldset>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">Radarr</legend>
                <Input placeholder="Radarr URL" value={radarrUrl} onChange={(e) => setRadarrUrl(e.target.value)} />
                <Input placeholder="Radarr API key" value={radarrKey} onChange={(e) => setRadarrKey(e.target.value)} />
              </fieldset>
              <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium">SFTP</legend>
                <Input placeholder="SFTP host" value={sftpHost} onChange={(e) => setSftpHost(e.target.value)} />
                <Input placeholder="SFTP username" value={sftpUser} onChange={(e) => setSftpUser(e.target.value)} />
                <Input placeholder="SFTP password" type="password" value={sftpPass} onChange={(e) => setSftpPass(e.target.value)} />
              </fieldset>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setStep("handbrake")} disabled={busy}>Skip</Button>
                <Button onClick={saveConnections} disabled={busy}>Save & continue</Button>
              </div>
            </div>
          )}

          {step === "handbrake" && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted">Path to HandBrakeCLI.exe (optional).</p>
              <Input placeholder="C:\\path\\to\\HandBrakeCLI.exe" value={handbrake}
                onChange={(e) => setHandbrake(e.target.value)} />
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setStep("done")} disabled={busy}>Skip</Button>
                <Button onClick={saveHandbrake} disabled={busy}>Save & continue</Button>
              </div>
            </div>
          )}

          {step === "done" && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted">You're all set.</p>
              <Button onClick={onDone}>Finish — go to dashboard</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

NOTE: confirm the `Button` `variant="secondary"` prop exists in
`solution/web/src/components/ui/button.tsx`. If the variant name differs, use
the existing one; if `Button` has no variants, drop the `variant` prop (the
Skip/Save buttons still work).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd solution/web && npm test -- Setup`
Expected: PASS (both tests).

- [ ] **Step 5: Typecheck + full frontend suite**

Run: `cd solution/web && npm test`
Expected: `tsc -b` clean, all Vitest pass.

- [ ] **Step 6: Commit**

```bash
git add solution/web/src/pages/Setup.tsx solution/web/src/pages/Setup.test.tsx
git commit -F <msgfile>   # "feat(web): first-run setup wizard (password + connections + HandBrake)"
```

---

### Task 6: Docs — `.env.example` and `CLAUDE.md`

**Files:**
- Modify: `solution/.env.example`
- Modify: `CLAUDE.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `.env.example`**

Prepend a comment block to `solution/.env.example` explaining the fields are now optional:

```
# All values below are OPTIONAL. A fresh install boots with no .env and walks you
# through setup in the browser (set a dashboard password, then connections). These
# env vars are only a fallback/override for the DB-stored settings. SECRET_KEY, if
# left unset, is auto-generated and persisted to a `secret_key` file next to the DB.
```

(Leave the existing example values below the comment as a reference.)

- [ ] **Step 2: Update `CLAUDE.md`**

In `CLAUDE.md`, find the Web UI line that reads "Requires `APP_PASSWORD` +
`SECRET_KEY` in `.env`." and replace it with:

```
A fresh install needs no `.env`: it boots to a first-run setup wizard (set a
dashboard password, then optionally Sonarr/Radarr/SFTP/HandBrake — all also
editable later in Settings). `SECRET_KEY` is read from `.env` if present, else
auto-generated and persisted to a `secret_key` file beside the DB. Providing
`APP_PASSWORD`/`SECRET_KEY` in `.env` still works and skips the password step.
```

- [ ] **Step 3: Sanity-check the suites still pass**

Run: `python -m pytest -q`
Run: `cd solution/web && npm test`
Expected: all pass (docs-only change; this just confirms nothing was disturbed).

- [ ] **Step 4: Commit**

```bash
git add solution/.env.example CLAUDE.md
git commit -F <msgfile>   # "docs: empty-install onboarding (optional .env, setup wizard)"
```

---

## Self-Review

**Spec coverage:**
- A. Boot without config → Task 1 ✓
- B. SECRET_KEY resolution → Task 2 ✓
- C. needs_setup detection + set-password endpoint → Task 3 ✓
- D. Setup wizard (gate + steps) → Tasks 4 & 5 ✓
- E. Tests → folded into each task (TDD) ✓
- F. Docs (.env.example, CLAUDE.md) → Task 6 ✓
- Backward compatibility (env present → no wizard) → covered by Task 3
  `test_me_no_setup_when_password_hash_exists` and Task 2 env-branch test ✓

**Placeholder scan:** none — every code/test step contains full content. The one
conditional note (Button `variant`) gives an explicit fallback rather than a TBD.

**Type consistency:** `resolve_secret_key()`, `_password_configured(db)`,
`needs_setup`, `POST /api/setup/password {password}`, and `Setup({ onDone })` are
named identically wherever referenced across tasks.
