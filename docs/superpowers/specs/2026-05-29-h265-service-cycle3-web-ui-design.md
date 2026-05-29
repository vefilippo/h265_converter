# H.265 Converter Service — Cycle 3: Web UI (Design Spec)

**Date:** 2026-05-29
**Status:** Approved (design)
**Scope:** Cycle 3 of 4 — a React single-page dashboard (served by FastAPI) with single-password auth, consuming the Cycle 2 API + SSE.

---

## 1. Context & Goal

Cycles 1–2 produced a DB-backed transcoder engine and a FastAPI service (library/scan/jobs/exclusions/status + SSE live progress, continuous background worker). Cycle 3 adds the **web dashboard** the service was always meant to have: browse the library, trigger scans, watch jobs progress live, and manage the queue/exclusions — behind a single-password login.

This is the last user-facing cycle; Cycle 4 (scheduling, notifications, run-as-service) follows.

### Fixed constraints (carried + decided in brainstorming)
- **Single local user on the LAN**, single box. One served URL.
- **React SPA (Vite + React + TypeScript + Tailwind + shadcn/ui)**, built to static files and served by FastAPI (one process). Not Next.js, not HTMX.
- **Single shared password** auth via a signed httponly session cookie.
- Consumes the **existing Cycle 2 API**; backend changes are limited to auth + static serving.
- Visual look/feel is produced with **`frontend-design-pro`** during implementation.

### Non-goals for Cycle 3
- No multi-user accounts/roles, no OAuth, no HTTPS automation (Cycle 4/ops).
- No scheduling, notifications, config editing from the UI (Cycle 4).
- No exhaustive UI test coverage — a focused set plus a manual pass.
- No new transcoding/engine behavior.

---

## 2. Architecture

- **`web/`** — a Vite React+TS app (Tailwind, shadcn/ui, React Router, TanStack Query). `npm run build` emits `web/dist`.
- **Serving:** FastAPI mounts the built assets and adds a **catch-all** route that returns `web/dist/index.html` for any non-`/api`, non-asset path (client-side routing). `/api/*` routes always take precedence; unknown `/api/*` still yields JSON 404, never the SPA shell.
- **Dev mode:** `npm run dev` runs the Vite dev server (default `:5173`) with a proxy: `/api` → `http://localhost:8765`. Backend runs via `python -m transcoder.api`. Hot-reload for the UI; API unchanged.
- **Prod mode:** build the SPA, then `python -m transcoder.api` serves both API and static UI on `API_HOST:API_PORT`.

### Data flow
SPA → `/api/*` (JSON, via TanStack Query) for reads/actions; SPA → `/api/stream` (SSE via `EventSource`) for live current-job progress + heartbeats. The session cookie authorizes both (EventSource sends cookies same-origin).

---

## 3. Authentication

- **Settings:** `APP_PASSWORD` (required) and `SECRET_KEY` (required) added to `transcoder/config.py`. Both come from `.env`.
- **Middleware:** Starlette `SessionMiddleware(secret_key=settings.SECRET_KEY, https_only=False, same_site="lax")` added in `create_app`.
- **Routes** (`transcoder/api/routers/auth.py`):
  - `POST /api/login` body `{password}` → if `password == settings.APP_PASSWORD`, set `request.session["authed"] = True`, return `{"ok": true}`; else `401`.
  - `POST /api/logout` → clear the session, return `{"ok": true}`.
  - `GET /api/me` → `{"authed": bool}` (lets the SPA decide whether to show login).
- **Guard:** a `require_auth` dependency raises `401` when `request.session` lacks `authed`. Applied to all `/api/*` routers **except** `auth` and `health`. Implementation: include the protected routers with `dependencies=[Depends(require_auth)]` in `create_app` (keeps each router file auth-agnostic).
- **SPA behavior:** on any `401` from the API, the client routes to the Login view. After successful login it returns to the intended view. `GET /api/me` is used on app load to pick the initial view.

---

## 4. Backend changes (summary)

| File | Change |
|---|---|
| `transcoder/config.py` | add `APP_PASSWORD: str`, `SECRET_KEY: str` (required), `WEB_DIST: str = "web/dist"` |
| `transcoder/api/auth.py` | `require_auth` dependency + login/logout/me routes (router) |
| `transcoder/api/app.py` | add `SessionMiddleware`; include protected routers with `dependencies=[Depends(require_auth)]`; mount static + SPA catch-all (only if `web/dist` exists, so the API still boots before the first UI build) |
| `.env.example` | add `APP_PASSWORD=`, `SECRET_KEY=` |

The library/scan/jobs/exclusions/stream routers are unchanged except for being mounted behind the auth dependency.

---

## 5. Frontend structure (`web/`)

```
web/
  index.html
  package.json            # vite, react, react-dom, react-router-dom, @tanstack/react-query,
                          # tailwindcss, shadcn deps, vitest, @testing-library/react
  vite.config.ts          # React plugin + dev proxy /api -> :8765 + test config
  tailwind.config.js / postcss.config.js
  src/
    main.tsx              # router + QueryClientProvider
    api/client.ts         # typed fetch wrapper (throws ApiError; 401 -> auth event)
    api/types.ts          # TS types mirroring the API schemas
    hooks/useEventStream.ts  # EventSource wrapper -> current job/progress
    hooks/queries.ts      # TanStack Query hooks (library, jobs, status, exclusions, stats)
    auth/AuthGate.tsx     # checks /api/me; renders Login or the app
    pages/Login.tsx
    pages/Dashboard.tsx   # status + current job (SSE) + queue + quick actions
    pages/Library.tsx     # paginated/filterable table; enqueue/exclude/scan
    pages/Jobs.tsx        # job list + detail; cancel/retry
    pages/Exclusions.tsx  # list/add/remove
    components/...         # shadcn-based: tables, dialogs, progress, badges, nav
```

### Screens
- **Dashboard:** worker-alive indicator; current job card with a live progress bar (from `/api/stream`); queue length + queued list; library stats; quick actions (Scan, Enqueue eligible). Scan shows running/done via `/api/scan/status`.
- **Library:** server-paginated table with `source`/`eligibility` filters; per-row actions — Enqueue (for `needs_transcode`), Exclude (adds a manual exclusion); a Scan button (with app/scope). Reflects the 5k+ item scale via pagination.
- **Jobs:** table of jobs (state badges, progress); row → detail (sizes, reduction %, error, output filename); Cancel (queued/running) and Retry (failed/skipped_larger/cancelled) actions.
- **Exclusions:** list with source/key/reason; add (manual) and delete; note that re-eligibility needs a re-scan.
- **Login:** single password field → `POST /api/login`.

### State/data
TanStack Query for all reads with sensible `staleTime` + invalidation after mutations (enqueue/cancel/retry/scan/exclude). Live progress comes from the SSE hook, not polling. Mutations surface errors via toast/inline.

---

## 6. Visual design

Before building the screens, run **`frontend-design-pro`** to establish the design system (palette, typography, spacing, component styling, dark mode) and produce styled component scaffolding. The implementation plan includes this as an explicit early step so the screens are built against a real design rather than ad-hoc styling. The chosen aesthetic is recorded in the plan/spec for consistency.

---

## 7. Testing

- **Backend (pytest):** login success → cookie set; wrong password → 401; protected route without session → 401; with session → 200; logout clears; `/api/me` reflects state; SPA catch-all returns `index.html` for a non-API path while `/api/unknown` returns JSON 404; API still boots when `web/dist` is absent.
- **Frontend (Vitest + React Testing Library):** focused set — `api/client` (success, `ApiError`, 401 handling), `useEventStream` (parses progress events; cleans up), and 1–2 key components (e.g., the Dashboard current-job/progress view and the Jobs row actions). Not exhaustive.
- **Manual:** a full end-to-end pass (login → dashboard → scan → watch a job → cancel/retry) documented for the user to run, since a real transcode needs eligible content + real SFTP creds.

---

## 8. Error handling

- API client maps non-2xx to a typed `ApiError`; `401` triggers the auth-required flow (route to Login).
- Mutations show user-facing error messages; queries show inline error/empty states.
- SSE hook reconnects on transient drop (EventSource default) and surfaces a "disconnected" indicator.
- Backend auth failures return JSON `{"detail": ...}` with the right status; the catch-all never masks `/api` errors.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Node/npm toolchain on Windows | Documented dev/build steps; FastAPI boots without `web/dist` so backend isn't blocked by the UI build |
| SPA catch-all shadowing API routes | Catch-all excludes `/api` and asset paths; tests assert `/api/unknown` → JSON 404 |
| Session cookie not sent to SSE | Same-origin `EventSource` sends cookies; served same-origin in prod, proxied in dev |
| Frontend scope creep | Four screens fixed; visuals delegated to frontend-design-pro; focused tests only |
| Secrets (APP_PASSWORD/SECRET_KEY) | Live only in `.env` (gitignored); `.env.example` lists them as blanks |

---

## Appendix — Roadmap position

1. **Foundation** — done, merged (Cycle 1).
2. **API + worker** — done, merged (Cycle 2).
3. **Web UI** *(this spec)* — React SPA dashboard + single-password auth, served by FastAPI.
4. **Automation** — scheduling, notifications, config editing from the UI, run-as-Windows-service.
