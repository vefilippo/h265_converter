# Scheduler & Settings Page — Design Spec

**Date:** 2026-05-31  
**Status:** Approved

---

## Overview

Add a cron-based automatic scan scheduler and a full Settings page to the h265 transcoder web UI. The scheduler fires the same "Run" flow (scan new + enqueue eligible) on a user-defined cron schedule. The Settings page exposes scheduler config plus all connection credentials, transcoding options, and the app password — making the app self-contained after initial `.env` bootstrap.

---

## Architecture

### Backend

#### `transcoder/scheduler.py` (new)
`SchedulerController` wraps APScheduler's `BackgroundScheduler`:
- `start(db)` — reads `scheduler_cron` and `scheduler_run_at_startup` from the `Setting` table, registers the cron job, optionally fires an immediate scan
- `shutdown()` — stops the scheduler gracefully
- `reschedule(db, cron: str | None, run_at_startup: bool)` — called live by the settings API when schedule keys change; no restart required
- The scheduled job calls the same internal `_run_full()` coroutine used by `POST /api/run`

#### `transcoder/api/routers/settings.py` (new)
Router mounted at `/api/settings`, all endpoints require auth:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Returns all editable settings; credential fields return `"••••••••"` |
| PUT | `/api/settings` | Saves a partial update; empty credential value = keep existing; triggers `reschedule()` if schedule keys change |

Validation: invalid cron expressions return `400`. Wrong `current_password` on password change returns `403`.

#### `transcoder/api/app.py` (updated)
- Add `SchedulerController` singleton to `state.py`
- Start scheduler in lifespan `startup`, shut it down in `shutdown`
- Seed all settings from `.env` into the `Setting` table on startup if the key is absent (one-time bootstrap per key)

#### `transcoder/api/state.py` (updated)
Add `scheduler: SchedulerController` singleton.

#### `transcoder/repo.py` (updated)
Add `get_effective(db, key: str, fallback: str) -> str` helper — returns DB value if present, otherwise falls back to the provided default. Used at all callsites that previously read directly from pydantic settings for: `sonarr_url`, `radarr_url`, `sonarr_api_key`, `radarr_api_key`, `sftp_host`, `sftp_port`, `sftp_username`, `sftp_password`, `handbrake_cli`, `handbrake_preset`.

---

## Data Model

All settings stored in the existing `Setting` table (key-value, SQLite). New keys:

### Scheduler (no `.env` equivalent)
| Key | Default | Notes |
|-----|---------|-------|
| `scheduler_cron` | `null` | cron string e.g. `"0 3 * * *"`; null = disabled |
| `scheduler_run_at_startup` | `"false"` | `"true"` / `"false"` |

### Connections (seeded from `.env`)
| Key | `.env` source |
|-----|--------------|
| `sonarr_url` | `SONARR_URL` |
| `sonarr_api_key` | `SONARR_API_KEY` |
| `radarr_url` | `RADARR_URL` |
| `radarr_api_key` | `RADARR_API_KEY` |
| `sftp_host` | `SFTP_HOST` |
| `sftp_port` | `SFTP_PORT` |
| `sftp_username` | `SFTP_USERNAME` |
| `sftp_password` | `SFTP_PASSWORD` |

### Transcoding (seeded from `.env`)
| Key | `.env` source | Default |
|-----|--------------|---------|
| `handbrake_cli` | `HANDBRAKE_CLI` | — |
| `handbrake_preset` | — | `"H.265 NVENC 1080p"` |

### Security
| Key | Notes |
|-----|-------|
| `app_password_hash` | bcrypt hash, seeded by hashing `APP_PASSWORD` from `.env` |

---

## API Contract

### GET /api/settings
```json
{
  "scheduler_cron": "0 3 * * *",
  "scheduler_run_at_startup": "false",
  "sonarr_url": "http://...",
  "sonarr_api_key": "••••••••",
  "radarr_url": "http://...",
  "radarr_api_key": "••••••••",
  "sftp_host": "192.168.x.x",
  "sftp_port": "22",
  "sftp_username": "••••••••",
  "sftp_password": "••••••••",
  "handbrake_cli": "C:\\...\\HandBrakeCLI.exe",
  "handbrake_preset": "H.265 NVENC 1080p",
  "scheduler_next_run": "2026-06-01T03:00:00"
}
```

### PUT /api/settings
Accepts any subset of the above keys (partial update). Additional fields for password change:
```json
{ "current_password": "old", "new_password": "new" }
```
- Empty string for a credential key = keep existing value
- Invalid cron → `400 { "detail": "Invalid cron expression" }`
- Wrong current password → `403`
- Success → `200 { "updated": ["scheduler_cron", ...] }`

---

## Frontend

### New page: `web/src/pages/Settings.tsx`
Route: `/settings`, protected by `AuthGate`.

Four collapsible sections, each with its own Save button:

**Scheduler**
- "Run at startup" checkbox
- Enable/disable schedule toggle
- Cron expression text input (shown when enabled)
- Live cronstrue preview: "Every day at 3:00 AM"
- "Next run: <datetime>" when a valid cron is active
- Link to crontab.guru

**Connections**
- Sonarr URL + API key (masked, show/hide toggle)
- Radarr URL + API key (masked, show/hide toggle)
- SFTP host, port, username, password (masked)

**Transcoding**
- HandBrake CLI path
- Preset dropdown: "H.265 NVENC 1080p" / "H.265 NVENC 2160p 4K"

**Security**
- Current password + new password + confirm new password (all masked)

Each section shows a success toast on save or an inline error message on failure.

### Dependencies
- `cronstrue` npm package — cron-to-English translation
- `apscheduler` pip package — backend scheduler

### Navigation
Add "Settings" link to the existing sidebar nav.

### API client
Add `getSettings()` and `updateSettings(section, payload)` to `web/src/api/`.

---

## Error Handling

- Invalid cron: validated backend (APScheduler's parser) + frontend (cronstrue parse error)
- Credential save with empty value: treated as "no change" — original value kept
- Scheduler job failure: logged to `log/api.log`; does not crash the server
- Settings page load failure: show error state with retry button

---

## Testing

- Backend: unit tests for `SchedulerController.reschedule()` (valid/invalid cron, null disables)
- Backend: settings router tests for GET/PUT including credential masking and password change flow
- Frontend: `npm test` covering Settings form validation and cronstrue preview rendering
