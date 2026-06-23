# First-run onboarding for an empty install — design

**Date:** 2026-06-24
**Status:** Approved (pending spec review)

## Problem

A freshly installed, unconfigured instance cannot boot. `transcoder/config.py`
declares ten fields as **required** and instantiates `Settings()` at import time:

```
SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY,
SFTP_HOST, SFTP_USERNAME, SFTP_PASSWORD, HANDBRAKE_CLI,
APP_PASSWORD, SECRET_KEY
```

With no `.env` (the file is gitignored and therefore absent from a fresh
install payload), pydantic raises a `ValidationError` with 10 missing-field
errors and the process dies before serving anything. The user can never reach
the UI to configure the app — even though the app is otherwise designed to store
connections and the login password in the **database** (`setting` table), read
back through `get_effective(db, key, fallback)` and written by the Settings page.

The onboarding path the code already intends — *boot empty → configure in the
UI* — is blocked purely by `config.py` requiring those env vars at startup.

## Goals

- A fresh install boots with no `.env` and serves the UI.
- First launch presents a **guided setup wizard**. The only required step is
  creating a dashboard password; connection settings and the HandBrake path are
  shown but skippable (configurable later in Settings).
- Existing installs (with a `.env` and/or a configured password) are unaffected:
  no wizard, identical behavior.

## Non-goals

- Installer writing a starter `.env` (unnecessary now that the app
  self-bootstraps).
- Connection validation as a gate to finish setup (kept skippable).
- Any change to how transcoding, scanning, or the worker behave.

## Design

### A. Boot without config (backend)

In `transcoder/config.py`, give the connection/credential fields a safe default
of `""` instead of leaving them required:

`SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`, `SFTP_HOST`,
`SFTP_USERNAME`, `SFTP_PASSWORD`, `HANDBRAKE_CLI`, `APP_PASSWORD`, `SECRET_KEY`.

This is safe because:

- These values are consumed via `get_effective(db, key, settings.X)`, so a DB
  value (set in the wizard / Settings) takes precedence and an empty fallback is
  only used when nothing is configured yet.
- `seed_settings_from_env(db, mapping)` already skips empty values
  (`if get_setting(...) is None and value`), so empty defaults never clobber or
  seed blank DB rows.
- A fully populated `.env` continues to load and seed exactly as today.

### B. SECRET_KEY resolution

`SECRET_KEY` signs session cookies and cannot be empty. The `SessionMiddleware`
is added inside `create_app()` **before** the lifespan runs `init_db()`, so the
DB is not guaranteed to exist at that point. Resolve the secret from a file, not
the DB:

Add a helper (e.g. `transcoder/config.py: resolve_secret_key()` or a small
`transcoder/secret.py`):

1. If env `SECRET_KEY` is non-empty, use it.
2. Else read a `secret_key` file located next to the database
   (`os.path.dirname(db_path_from_url(settings.DATABASE_URL))`).
3. Else generate `secrets.token_urlsafe(48)`, write it to that file
   (create parent dir if needed), and use it.

`app.py` uses the resolved value:
`app.add_middleware(SessionMiddleware, secret_key=resolve_secret_key(), same_site="lax")`.

The secret persists across restarts (sessions survive). If the file is lost,
a new secret is generated and existing sessions simply require re-login.

### C. First-run detection + set-password endpoint (backend)

**Detection.** "Needs setup" is defined as *no password configured*:

```
needs_setup = get_setting(db, "app_password_hash") is None and not settings.APP_PASSWORD
```

Existing installs with a hash or a non-empty `APP_PASSWORD` env → `needs_setup`
is `False`, so the wizard never appears (backward compatible).

**Expose it.** Extend `GET /api/me` response from `{authed}` to
`{authed, needs_setup}`.

**Set the initial password.** New open (unauthenticated) endpoint:

```
POST /api/setup/password   body: {password: str}
```

- Allowed only when `needs_setup` is true. If a password already exists, return
  **409 Conflict** (prevents an unauthenticated takeover of a configured
  instance).
- On success: store `app_password_hash` (bcrypt) via `set_setting`, mark the
  session authed (`request.session["authed"] = True`), return `{ok: true}`.
- Reject empty/blank passwords with 422/400.

Connection steps in the wizard run *after* the password is set and the session
is authed, so they reuse the existing authenticated `PUT /api/settings` — no new
endpoints for connections.

### D. Setup wizard (frontend)

- `auth/useMe.ts` surfaces `needs_setup` from `GET /api/me`.
- `auth/AuthGate.tsx`: when `needs_setup` is true, render a new `<Setup />`
  wizard (in place of Login and the app). When false, the current
  Login → app flow is unchanged.
- New `pages/Setup.tsx` wizard:
  1. **Create password** (required). Submits `POST /api/setup/password`; on
     success the session is authed. Then refetch `/api/me` so `needs_setup`
     becomes false.
  2. **Connections** — Sonarr URL/key, Radarr URL/key, SFTP host/port/user/pass.
     "Skip" and "Save & continue" both advance; Save calls `PUT /api/settings`.
  3. **HandBrake path** — optional text field; Skip or Save (`PUT /api/settings`).
  4. **Finish** → navigate to Dashboard.
- Reuse existing form primitives/components from the Settings page where
  practical to avoid duplicating connection-field UI.

### E. Tests

Backend (pytest, TDD — failing test first):

- `Settings()` (and `Settings(_env_file=None)` with a cleared environment) loads
  without raising; defaults are `""`.
- `resolve_secret_key()`: generates and writes a file when none exists; returns
  the same value on a second call; prefers a non-empty env value.
- `GET /api/me` returns `needs_setup: true` on an empty DB, `false` once a
  password hash exists.
- `POST /api/setup/password` sets the hash and authes the session when none
  exists; returns 409 when a password already exists; rejects blank input.

Frontend (Vitest):

- `AuthGate` renders `<Setup>` when `/api/me` reports `needs_setup`.
- The password step posts to `/api/setup/password` and advances on success.
- Connection and HandBrake steps are skippable (Finish reachable after password
  only).

### F. Docs

- `.env.example`: note that connection fields are optional (configurable in the
  setup wizard / Settings); `SECRET_KEY` auto-generates if unset.
- `CLAUDE.md`: update the line stating `APP_PASSWORD` + `SECRET_KEY` are required
  in `.env` to reflect the first-run wizard + auto-generated secret.

## Backward compatibility

- Installs with a `.env` and/or an `app_password_hash`: `needs_setup` is false,
  `SECRET_KEY` comes from env — no wizard, no behavior change.
- The set-password endpoint is inert (409) once any password exists.

## Affected files

- `solution/transcoder/config.py` — optional defaults, `resolve_secret_key()`.
- `solution/transcoder/api/app.py` — use resolved secret key.
- `solution/transcoder/api/auth.py` — `needs_setup` in `/api/me`; `/api/setup/password`.
- `solution/web/src/auth/useMe.ts`, `auth/AuthGate.tsx` — gate the wizard.
- `solution/web/src/pages/Setup.tsx` — new wizard.
- Tests under `tests/` and `solution/web/src/**`.
- `.env.example`, `CLAUDE.md`.
