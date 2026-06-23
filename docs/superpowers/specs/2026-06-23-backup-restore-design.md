# Backup & Restore — Design

**Date:** 2026-06-23
**Status:** Approved (design)

## Goal

Let an operator take a **full state backup** of a running H.265 Transcoder
instance from the web UI, and **restore** it onto a new instance (a freshly
installed copy on another box) so the new instance becomes a clone of the old
one. This replaces the error-prone manual "stop the service, copy `transcoder.db`
and `.env` by hand" dance.

## Scope

In scope (YAGNI — manual, on-demand only):

- **Download backup** from the Settings page.
- **Restore from backup** from the Settings page, turnkey with auto-restart.

Explicitly out of scope:

- Scheduled/automatic backups.
- Server-side backup retention, history, or listing.
- Cloud/remote upload of backups.
- Backing up the venv (not portable — the new instance already has its own venv
  from install; state-only backups + that venv is sufficient).
- Merge semantics. Restore is **wholesale replace** of DB + `.env` ("clone this
  instance"), not a merge.

## Backup contents

A single `backup.zip`:

| Entry | What | Notes |
|---|---|---|
| `transcoder.db` | Consistent SQLite snapshot | Taken live via SQLite online backup (`VACUUM INTO` to a temp file), safe while the app runs and holds the DB open. |
| `env.enc` | The instance `.env`, encrypted | AES-256-GCM; key = scrypt(passphrase, salt). Holds all secrets (API keys, SFTP password, `APP_PASSWORD`, `SECRET_KEY`). |
| `manifest.json` | Metadata for validation | `{app, schema_version, app_version, created_at, kdf, kdf_params, salt, nonce}`. |

**Crypto:** use the `cryptography` package — **confirmed present** (v49.0.0,
`AESGCM` + `Scrypt`) transitively via `paramiko`, which is in `requirements.txt`,
so the installed instance gets it too. AES-256-GCM for authenticated encryption
(detects tampering / wrong key), scrypt for the KDF. `salt` and `nonce` are
random per backup and stored in the manifest (they are not secret).

**Why encrypt `.env` but not the DB:** the DB holds operational state (jobs,
exclusions, library, settings); the secrets live in `.env`. Encrypting `.env`
keeps a downloaded backup from leaking credentials if it lands in Downloads /
cloud sync. The DB is left plain so a backup is still inspectable; revisit if DB
contents are later deemed sensitive.

## Backup flow

1. Settings → **Download backup** → operator enters a passphrase.
2. `POST /api/backup` body `{passphrase}` (auth-gated like every other endpoint).
3. Server: snapshot the DB to a temp dir, encrypt `.env` → `env.enc`, write
   `manifest.json`, zip the three, **stream** the zip with
   `Content-Disposition: attachment; filename="h265-backup-YYYYMMDD.zip"`, then
   delete the temp dir.
4. Browser saves the file (fetch → blob; POST is used because of the passphrase
   body + session auth).

No backup is retained server-side.

## Restore flow (turnkey, auto-restart)

1. Settings → **Restore from backup** → operator picks a `backup.zip` + passphrase.
2. `POST /api/restore` (multipart: `file`, `passphrase`).
3. Server:
   a. Validate `manifest.json` (`app` matches; refuse if `schema_version` is
      **newer** than this instance understands).
   b. Decrypt `env.enc` with the passphrase. Wrong passphrase or tampering →
      GCM auth failure → `400 {detail: "wrong passphrase or corrupt backup"}`,
      **nothing staged or changed**.
   c. Stage the new `transcoder.db` and decrypted `.env` text into a
      `restore_pending/` directory next to the DB, plus a `RESTORE_PENDING`
      marker file.
   d. Spawn a **detached relauncher** process (survives parent exit) that waits
      for the API port to free, then starts `transcoder.api` again with the
      correct interpreter + cwd; return `202 {status: "restarting"}`; the current
      server process exits shortly after responding.
4. **Startup bootstrap** — in `api/app.py` lifespan, **before** `init_db()` and
   before any DB engine work: if the `RESTORE_PENDING` marker exists, atomically
   replace `transcoder.db` with the staged copy, write `.env` from the staged
   text, remove the staged dir + marker, then continue normal boot.
5. UI shows "restarting / reconnecting…" and polls `/api/health` until it
   returns `ok`, then reloads.

### Relauncher rationale

The tray (`tray.pyw`) is the normal supervisor but does **not** auto-restart the
server if it exits (the poll loop only repaints the status icon). Rather than add
desired-state supervision to the tray (broader behavior change), the restart is
**app-owned**: the API spawns a small detached relauncher so restore works
identically whether launched via tray or headless `run.bat`. The relauncher uses
`sys.executable`/the venv `pythonw.exe` and `cwd = <package dir>` (so the
cwd-relative `transcoder.db` resolves correctly, consistent with how `tray.pyw`
launches the server today).

## Components

Each unit has one purpose, a clear interface, and is testable in isolation.

- **`transcoder/backup.py`** — backup assembly + crypto (mostly pure):
  - `snapshot_db(db_path, dest) -> Path` — consistent SQLite copy.
  - `encrypt_env(env_text, passphrase) -> (cipher_bytes, kdf_params)` /
    `decrypt_env(cipher_bytes, passphrase, kdf_params) -> str`.
  - `build_manifest(...) -> dict` / `validate_manifest(dict) -> None` (raises).
  - `make_backup(db_path, env_path, passphrase) -> bytes` (zip bytes).
  - `read_backup(zip_bytes, passphrase) -> (db_bytes, env_text, manifest)`.
- **`transcoder/restore.py`** — staging + bootstrap + relaunch (I/O):
  - `stage_restore(db_bytes, env_text, base_dir) -> None` (writes pending dir + marker).
  - `apply_pending_restore(base_dir) -> bool` — the startup bootstrap; returns
    whether a restore was applied. Pure-enough to unit-test with a temp dir.
  - `schedule_relaunch()` — spawn the detached relauncher; thin, not unit-tested.
- **`api/routers/backup.py`** — `POST /api/backup`, `POST /api/restore`
  (both `require_auth`).
- **`api/app.py`** lifespan — call `apply_pending_restore(<db dir>)` **before**
  `init_db()`.
- **Web** — a "Backup & Restore" card on the Settings page; `useBackup()` /
  `useRestore()` hooks in `web/src/`; an API client method each.

## Error handling

- Wrong passphrase / corrupt zip → `400`, nothing changed (validation + decrypt
  happen before any staging).
- Manifest `app` mismatch or `schema_version` newer than current → `400` with a
  clear message; refuse.
- Snapshot failure (disk full, locked) → `500`, temp cleaned up, no partial file
  streamed.
- Restore staging failure → `500`, no marker written (so a half-staged restore is
  never applied at next boot).
- Bootstrap apply failure (e.g., can't replace DB) → log loudly, leave the marker
  so it retries next boot; do not delete the existing good DB until the staged
  copy is in place (write to a temp name + atomic replace).

## Testing (TDD)

- **Unit (`backup.py`):** encrypt→decrypt round-trips; wrong passphrase raises;
  tampered ciphertext raises; manifest build/validate (good + each rejection
  case); zip pack→unpack preserves bytes; `snapshot_db` produces a readable DB
  with the same row counts.
- **Unit (`restore.py`):** `stage_restore` writes pending dir + marker;
  `apply_pending_restore` swaps DB + writes `.env` + clears marker; no-op when no
  marker; retains marker on simulated apply failure.
- **API:** `/api/backup` requires auth and returns a zip containing the three
  entries; `/api/restore` with a good zip stages files + marker and returns 202
  (relaunch mocked); with a bad passphrase returns 400 and stages nothing.
- **Frontend:** Settings card renders; download triggers `POST /api/backup` with
  the passphrase and saves a blob; restore posts file + passphrase and shows the
  reconnecting state; the suite typechecks (`tsc -b`).

## Security notes

- Both endpoints are behind the existing single-password session auth.
- The passphrase is never persisted; it exists only for the duration of a
  request. `salt`/`nonce` in the manifest are non-secret by design.
- A downloaded backup's secrets are protected only as well as the passphrase —
  the UI should advise choosing a strong one.

## Files touched

- New: `solution/transcoder/backup.py`, `solution/transcoder/restore.py`,
  `solution/transcoder/api/routers/backup.py`, tests under `tests/`.
- New web: a Settings "Backup & Restore" card + hooks + client methods + tests.
- Modified: `solution/transcoder/api/app.py` (register router + bootstrap call),
  `CLAUDE.md` / `README.md` (document the feature + endpoints).
