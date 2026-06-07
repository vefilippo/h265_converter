# Sonarr/Radarr Webhook Trigger — Design

**Date:** 2026-06-07
**Status:** Approved (pending implementation plan)

## Summary

Add an **inbound** webhook so Sonarr and Radarr trigger this app the moment a
file is imported, instead of waiting for a manual, scheduled, or watermark
"new" scan. On receipt the app discovers just that one series/movie, enqueues
it if it's eligible for transcoding, and wakes the background worker.

This is event-driven discovery layered on top of the existing poll-based
discovery — both continue to work.

## Decisions (from brainstorming)

- **Direction:** inbound trigger. Sonarr/Radarr call us; we react instantly.
- **Auth:** HTTP Basic. Both apps expose username/password fields on a webhook
  connection. The endpoint cannot use the session-cookie `require_auth` the
  other routers share, so it self-authenticates.
- **Reaction:** targeted single item — reuse `discover_sonarr(target_title=…)` /
  `discover_radarr(target_movie=…)`, not a full/"new" scan.
- **Config surface:** the existing Settings page (web UI), stored in the
  `setting` table like other config.

## Architecture & request flow

```
Sonarr/Radarr  ──HTTP POST (Basic auth)──▶  POST /api/webhook/{source}
                                                  │
                                    verify Basic auth (settings creds)
                                                  │ 200 returned immediately
                                                  ▼
                                BackgroundTasks: _process_webhook(source, title)
                                                  │  (coalescer dedupes bursts)
                                                  ▼
                  discover_sonarr(target_title=…) / discover_radarr(target_movie=…)
                                                  ▼
                             enqueue_eligible(source=…) → controller.wake()
```

The endpoint is registered as an **open** router (alongside `/api/health` and
`auth_router`), *not* behind `require_auth`, and enforces its own HTTP Basic
check. It returns `200` before doing discovery so Sonarr/Radarr get a fast
response.

## Components

### New — `source_code/transcoder/api/routers/webhook.py`

- `POST /api/webhook/{source}` where `source` ∈ `sonarr` | `radarr`
  (otherwise `404`).
- `_verify_basic(request)`: reads `Authorization: Basic`, decodes, compares
  username with `hmac.compare_digest` and the password with `bcrypt.checkpw`
  against the `webhook_username` / `webhook_password_hash` settings. On failure
  → `401` + `WWW-Authenticate: Basic`. If no credentials are configured → `401`.
- Parses the JSON body. Acts only on `eventType == "Download"` (Sonarr/Radarr's
  import event). `"Test"` and all other event types → `200` ack with no work
  (so the Test button in Sonarr/Radarr succeeds).
- Extracts the title:
  - Sonarr: `payload["series"]["title"]`
  - Radarr: `payload["movie"]["title"]`
  - Missing/unexpected shape → `200` ack + warning log, no work.
- Schedules `_process_webhook(source, title)` via `BackgroundTasks`.

### Background — `_process_webhook(source, title)`

- Coalescer guard: an in-memory `set[(source, title)]` protected by a lock. If
  the pair is already pending, skip scheduling a duplicate; otherwise add it,
  do the work, and remove it in a `finally`.
- Builds clients via `build_clients()`, opens a fresh `SessionLocal()`, runs the
  targeted `discover_*` with `scope="all"` plus the target title (so it does
  **not** read or advance the watermark), then `enqueue_eligible(source=source)`
  and `controller.wake()`.
- Logs received event and resulting counts to the `transcoder` logger so they
  appear on the Logs page.

### Settings — `routers/settings.py` + `schemas.py`

- New settings keys: `webhook_username`, `webhook_password_hash`.
- `SettingsOut` gains `webhook_username` and `webhook_password_set: bool`.
- `SettingsUpdate` gains `webhook_username` and `webhook_password`
  (bcrypt-hashed on save, mirroring `app_password`; never returned).

### Wiring — `api/app.py`

- `app.include_router(webhook.router)` with **no** `require_auth` dependency
  (registered next to the open health/auth routes).

### Web UI — Settings page (`source_code/web/`)

- A "Webhooks" section that:
  - Shows the two copy-able URLs: `<this-host>/api/webhook/sonarr` and
    `<this-host>/api/webhook/radarr`.
  - Provides a username field and a write-only password field that reports
    "set" / "not set" via `webhook_password_set`.
  - Shows a one-line note: the host must be reachable from the Sonarr/Radarr
    machine, and the connection should fire on the import events ("On Import" /
    "On Import Upgrade").

## Error handling & edge cases

- **Auth fail** → `401` + `WWW-Authenticate: Basic`.
- **Bad JSON** → `400`; **unknown source** → `404`.
- **Missing title / non-import event** → `200` ack, no work (never make
  Sonarr/Radarr show a failed webhook for benign events such as Test).
- **Background discovery error** → logged only; the `200` already returned.
- **Feedback loop** → broken naturally: after we upload the transcoded H.265
  file, Sonarr/Radarr re-import it and fire another webhook, but the file is now
  H.265 → eligibility is "not needed" → nothing enqueued.
- **Bursts** (season-pack imports) → the coalescer collapses repeat
  `(source, title)` pairs into a single discover.
- **Concurrency** → a targeted single-title discover is a small, batched-commit
  write; it coexists with the worker/API writers the same way scans already do.
  It deliberately does **not** take the full-scan `scan_status` lock — it is
  independent and lightweight.

## Testing

- **Unit:** `_verify_basic` (valid / invalid / missing header / no creds
  configured); title extraction for both payload shapes; `Test` event and
  missing-title produce no background work; unknown source → `404`.
- **API (FastAPI TestClient):** `200` with valid Basic auth (discover/enqueue
  mocked) and a background task scheduled; `401` without auth; coalescer
  dedupes two rapid identical posts into one discover.
- **Frontend:** the Settings "Webhooks" section renders; setting username and
  password issues the expected PUT (mirrors existing settings tests).

## Out of scope (YAGNI)

- Outbound notifications to the user (phone/Discord/desktop) — separate feature.
- Acting on non-import events (Grab, Rename, delete).
- HMAC payload signing (Sonarr/Radarr don't sign payloads natively).
