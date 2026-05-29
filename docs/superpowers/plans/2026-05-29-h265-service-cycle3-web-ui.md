# H.265 Service — Cycle 3 (Web UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A React SPA dashboard (Vite + Tailwind + shadcn/ui) served by FastAPI behind a single-password login, consuming the Cycle 2 API + SSE — screens for Dashboard, Library, Jobs, and Exclusions.

**Architecture:** Backend gains session-cookie auth (Starlette `SessionMiddleware` + a `require_auth` dependency protecting the API routers) and static serving of the built SPA with a catch-all for client routes. The `web/` Vite app uses TanStack Query for data, an `EventSource` hook for live progress, and React Router for the screens. Visual design is produced with `frontend-design-pro`.

**Tech Stack:** Backend: FastAPI, Starlette SessionMiddleware, SQLAlchemy, pytest. Frontend: Node 24 / npm 11, Vite, React 18 + TypeScript, Tailwind, shadcn/ui, React Router, TanStack Query, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-05-29-h265-service-cycle3-web-ui-design.md`

**Working dirs:** backend in `source_code/` (`.venv/Scripts/python.exe`); frontend in `source_code/web/` (`npm`). Branch: `cycle-3-web-ui`.

---

## Phase A — Backend: auth + static serving

## Task 1: Auth/web settings + test env

**Files:** Modify `source_code/transcoder/config.py`, `source_code/.env.example`, `source_code/tests/conftest.py`; Test: `source_code/tests/test_config.py`

- [ ] **Step 1: Add settings.** In `transcoder/config.py`, add to the required block (after `HANDBRAKE_CLI`):
```python
    APP_PASSWORD: str
    SECRET_KEY: str
```
and to the defaulted block (after `API_PORT`):
```python
    WEB_DIST: str = "web/dist"
```

- [ ] **Step 2: conftest env defaults.** In `tests/conftest.py`, add alongside the other `os.environ.setdefault(...)` lines:
```python
os.environ.setdefault("APP_PASSWORD", "test-pass")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
```

- [ ] **Step 3: `.env.example`.** Append:
```
APP_PASSWORD=choose_a_dashboard_password
SECRET_KEY=generate_a_long_random_string
```

- [ ] **Step 4: Test.** Append to `tests/test_config.py`:
```python
def test_settings_web_auth_defaults():
    from transcoder.config import settings
    assert settings.WEB_DIST == "web/dist"
    assert settings.APP_PASSWORD  # provided by conftest env
    assert settings.SECRET_KEY
```

- [ ] **Step 5: Run** `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_config.py -q`. Expect 4 passed.
- [ ] **Step 6: Run full suite** — expect 56 passed (55 + 1). Note: the local `.env` must also gain `APP_PASSWORD`/`SECRET_KEY` for the real server to boot; tests rely on conftest env.
- [ ] **Step 7: Commit**
```bash
git add source_code/transcoder/config.py source_code/.env.example source_code/tests/conftest.py source_code/tests/test_config.py
git commit -m "feat: add APP_PASSWORD/SECRET_KEY/WEB_DIST settings"
```

---

## Task 2: Auth router + require_auth dependency

**Files:** Create `source_code/transcoder/api/auth.py`; Test: `source_code/tests/test_api_auth.py`

- [ ] **Step 1: Write the failing test** `tests/test_api_auth.py` (uses an app with SessionMiddleware; we build a tiny app here so the test is independent of app.py wiring, which Task 3 handles):
```python
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from transcoder.api.auth import router as auth_router, require_auth


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key")
    app.include_router(auth_router)

    @app.get("/api/secret", dependencies=[Depends(require_auth)])
    def secret():
        return {"ok": True}

    return TestClient(app)


def test_me_unauthed(client):
    assert client.get("/api/me").json() == {"authed": False}


def test_protected_requires_auth(client):
    assert client.get("/api/secret").status_code == 401


def test_login_wrong_password(client):
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401


def test_login_then_access_then_logout(client):
    assert client.post("/api/login", json={"password": "test-pass"}).json() == {"ok": True}
    assert client.get("/api/me").json() == {"authed": True}
    assert client.get("/api/secret").status_code == 200
    assert client.post("/api/logout").json() == {"ok": True}
    assert client.get("/api/secret").status_code == 401
```
(The test password `test-pass` matches the conftest `APP_PASSWORD`.)

- [ ] **Step 2: Run, confirm FAIL** (`No module named transcoder.api.auth`).

- [ ] **Step 3: Create `transcoder/api/auth.py`:**
```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from transcoder.config import settings

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    password: str


def require_auth(request: Request) -> None:
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="authentication required")


@router.post("/login")
def login(body: LoginIn, request: Request):
    if body.password != settings.APP_PASSWORD:
        raise HTTPException(status_code=401, detail="invalid password")
    request.session["authed"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {"authed": bool(request.session.get("authed"))}
```

- [ ] **Step 4: Run, confirm PASS** (`.venv/Scripts/python.exe -m pytest tests/test_api_auth.py -v`). 4 passed.
- [ ] **Step 5: Full suite** — expect 60 passed (56 + 4).
- [ ] **Step 6: Commit**
```bash
git add source_code/transcoder/api/auth.py source_code/tests/test_api_auth.py
git commit -m "feat: session-cookie auth router + require_auth dependency"
```

---

## Task 3: Wire auth into the app + update the API fixture

**Files:** Modify `source_code/transcoder/api/app.py`, `source_code/tests/api_conftest.py`; Test: `source_code/tests/test_api_protected.py`

- [ ] **Step 1: Write the failing test** `tests/test_api_protected.py`:
```python
def test_routers_protected_without_session(api):
    # The `api` fixture is authenticated; logout then verify protection.
    client, Session = api
    client.post("/api/logout")
    assert client.get("/api/library").status_code == 401
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/status").status_code == 401
    # health stays open
    assert client.get("/api/health").status_code == 200


def test_reauth_restores_access(api):
    client, Session = api
    client.post("/api/logout")
    assert client.get("/api/library").status_code == 401
    client.post("/api/login", json={"password": "test-pass"})
    assert client.get("/api/library").status_code == 200
```

- [ ] **Step 2: Run, confirm FAIL** — currently routers are unprotected, so `/api/library` after logout returns 200, failing the assertion.

- [ ] **Step 3: Modify `transcoder/api/app.py`.** Add the SessionMiddleware and protect the data routers. Replace the router-include section and add middleware:
```python
from starlette.middleware.sessions import SessionMiddleware
from fastapi import Depends
from transcoder.config import settings
from transcoder.api.auth import router as auth_router, require_auth
```
In `create_app`, after `app = FastAPI(... lifespan=lifespan)` and the `health` route, add:
```python
    app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, same_site="lax")

    # Open routes: health (defined above) + auth.
    app.include_router(auth_router)

    # Protected API routers.
    from transcoder.api.routers import library, scan, jobs, exclusions, stream
    protected = [Depends(require_auth)]
    app.include_router(library.router, dependencies=protected)
    app.include_router(scan.router, dependencies=protected)
    app.include_router(jobs.router, dependencies=protected)
    app.include_router(exclusions.router, dependencies=protected)
    app.include_router(stream.router, dependencies=protected)
    return app
```
(Remove the previous unprotected `include_router` block for these five.)

- [ ] **Step 4: Update `tests/api_conftest.py`** so the `api` fixture is authenticated by default (otherwise every existing API test would now 401). After creating `client = TestClient(app)`, add a login before yielding:
```python
    client = TestClient(app)
    client.post("/api/login", json={"password": "test-pass"})  # authenticate by default
    yield client, Session
    client.close()
```

- [ ] **Step 5: Run, confirm PASS** (`.venv/Scripts/python.exe -m pytest tests/test_api_protected.py -v`). 2 passed.
- [ ] **Step 6: Full suite** — expect 62 passed (60 + 2). All prior API tests still pass because the fixture now logs in.
- [ ] **Step 7: Commit**
```bash
git add source_code/transcoder/api/app.py source_code/tests/api_conftest.py source_code/tests/test_api_protected.py
git commit -m "feat: protect API routers behind session auth; auto-login test fixture"
```

---

## Task 4: Static serving + SPA catch-all

**Files:** Modify `source_code/transcoder/api/app.py`; Test: `source_code/tests/test_api_spa.py`

- [ ] **Step 1: Write the failing test** `tests/test_api_spa.py`:
```python
from fastapi.testclient import TestClient
import transcoder.api.app as app_module
from transcoder.api.app import create_app


def test_spa_served_when_dist_exists(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module.settings, "WEB_DIST", str(dist))

    app = create_app(start_worker=False)
    with TestClient(app) as client:
        # client-side route returns the SPA shell
        r = client.get("/library")
        assert r.status_code == 200 and "<title>app</title>" in r.text
        # asset served
        assert client.get("/assets/app.js").status_code == 200
        # unknown API path is JSON 404, NOT the SPA shell
        r404 = client.get("/api/does-not-exist")
        assert r404.status_code == 404
        assert "<title>app</title>" not in r404.text


def test_app_boots_without_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)
    monkeypatch.setattr(app_module.settings, "WEB_DIST", str(tmp_path / "missing"))
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
```

- [ ] **Step 2: Run, confirm FAIL** (no static handling yet; `/library` 404s).

- [ ] **Step 3: Modify `transcoder/api/app.py`.** At the END of `create_app` (just before `return app`), add static mounting + catch-all:
```python
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
```
Note: the catch-all is registered LAST so all explicit `/api/...` routes win; only unmatched paths reach it, and `api/`-prefixed misses return JSON 404.

- [ ] **Step 4: Run, confirm PASS** (`.venv/Scripts/python.exe -m pytest tests/test_api_spa.py -v`). 2 passed.
- [ ] **Step 5: Full suite** — expect 64 passed (62 + 2).
- [ ] **Step 6: Commit**
```bash
git add source_code/transcoder/api/app.py source_code/tests/test_api_spa.py
git commit -m "feat: serve built SPA with client-route catch-all (API 404s stay JSON)"
```

---

## Phase B — Frontend: scaffold + infrastructure

## Task 5: Vite React app scaffold

**Files:** Create under `source_code/web/`: `package.json`, `vite.config.ts`, `tsconfig.json`, `tailwind.config.js`, `postcss.config.js`, `index.html`, `src/main.tsx`, `src/index.css`, `src/App.tsx`, `src/setupTests.ts`, `src/smoke.test.tsx`; Modify `.gitignore`

- [ ] **Step 1: Gitignore node_modules + dist.** Append to root `.gitignore`:
```
# Frontend
source_code/web/node_modules/
source_code/web/dist/
```

- [ ] **Step 2: Create `web/package.json`:**
```json
{
  "name": "h265-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 3: `web/vite.config.ts`:**
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8765" },
  },
  build: { outDir: "dist" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

- [ ] **Step 4:** `web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

- [ ] **Step 5:** `web/tailwind.config.js`:
```js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```
`web/postcss.config.js`:
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 6:** `web/index.html`:
```html
<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>H.265 Transcoder</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

- [ ] **Step 7:** `web/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```
`web/src/App.tsx`:
```tsx
export default function App() {
  return <div className="p-4 text-lg">H.265 Transcoder</div>;
}
```
`web/src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>
);
```
`web/src/setupTests.ts`:
```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 8: Smoke test** `web/src/smoke.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders app title", () => {
  render(<App />);
  expect(screen.getByText("H.265 Transcoder")).toBeInTheDocument();
});
```

- [ ] **Step 9: Install + test.** Run: `cd source_code/web && npm install` then `npm test`.
Expected: install succeeds; vitest runs `smoke.test.tsx` → 1 passed.

- [ ] **Step 10: Build check.** Run: `npm run build`. Expected: `web/dist/index.html` + `web/dist/assets/*` produced.

- [ ] **Step 11: Commit** (node_modules/dist are gitignored):
```bash
git add .gitignore source_code/web/package.json source_code/web/package-lock.json source_code/web/vite.config.ts source_code/web/tsconfig.json source_code/web/tailwind.config.js source_code/web/postcss.config.js source_code/web/index.html "source_code/web/src"
git commit -m "feat: scaffold Vite React+TS web app (tailwind, vitest)"
```

---

## Task 6: API client + types

**Files:** Create `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/client.test.ts`

- [ ] **Step 1: Write the failing test** `web/src/api/client.test.ts`:
```ts
import { afterEach, expect, test, vi } from "vitest";
import { api, ApiError } from "./client";

afterEach(() => vi.restoreAllMocks());

test("GET returns parsed json", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ total: 0, items: [] }), { status: 200 })
  ));
  const data = await api.get<{ total: number }>("/api/jobs");
  expect(data.total).toBe(0);
});

test("non-2xx throws ApiError with status", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ detail: "nope" }), { status: 401 })
  ));
  await expect(api.get("/api/library")).rejects.toMatchObject({ status: 401 });
  expect(ApiError).toBeTruthy();
});
```

- [ ] **Step 2: Run, confirm FAIL** (`cd source_code/web && npx vitest run src/api/client.test.ts`).

- [ ] **Step 3: Create `web/src/api/types.ts`:**
```ts
export interface MediaItem {
  id: number; source: string; external_id: string; title: string;
  season: number | null; episode: number | null; year: number | null;
  resolution: number; quality: string | null; languages: string | null;
  codec: string | null; is_h265: boolean; eligibility: string;
}
export interface LibraryPage { total: number; items: MediaItem[]; }
export interface StatRow { source: string; eligibility: string; count: number; }
export interface Job {
  id: number; media_item_id: number; state: string; progress: number;
  preset: string | null; original_size: number | null; output_size: number | null;
  reduction_pct: number | null; output_filename: string | null;
  error_message: string | null; title: string | null;
}
export interface JobPage { total: number; items: Job[]; }
export interface Exclusion { id: number; source: string; key: string; reason: string; }
export interface Status {
  worker_alive: boolean; current_job: Job | null; queue_length: number; stats: StatRow[];
}
export interface ScanStatus {
  state: string; detail: Record<string, unknown>;
  started_at: string | null; finished_at: string | null;
}
```

- [ ] **Step 4: Create `web/src/api/client.ts`:**
```ts
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = (j && (j.detail as string)) || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
};
```

- [ ] **Step 5: Run, confirm PASS** (`npx vitest run src/api/client.test.ts`). 2 passed.
- [ ] **Step 6: Commit**
```bash
git add source_code/web/src/api
git commit -m "feat: typed API client + types"
```

---

## Task 7: Query hooks + SSE hook

**Files:** Create `web/src/hooks/queries.ts`, `web/src/hooks/useEventStream.ts`, `web/src/hooks/useEventStream.test.ts`

- [ ] **Step 1: Write the failing test** `web/src/hooks/useEventStream.test.ts` (mock EventSource):
```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useEventStream } from "./useEventStream";

class FakeES {
  onmessage: ((e: MessageEvent) => void) | null = null;
  listeners: Record<string, (e: MessageEvent) => void> = {};
  url: string;
  closed = false;
  constructor(url: string) { this.url = url; instances.push(this); }
  addEventListener(type: string, cb: (e: MessageEvent) => void) { this.listeners[type] = cb; }
  close() { this.closed = true; }
  emit(type: string, data: unknown) {
    this.listeners[type]?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}
const instances: FakeES[] = [];

afterEach(() => { instances.length = 0; vi.restoreAllMocks(); });

test("parses progress events and cleans up", () => {
  vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);
  const { result, unmount } = renderHook(() => useEventStream("/api/stream"));
  act(() => instances[0].emit("progress", { id: 5, progress: 42, title: "X" }));
  expect(result.current?.progress).toBe(42);
  unmount();
  expect(instances[0].closed).toBe(true);
});
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Create `web/src/hooks/useEventStream.ts`:**
```ts
import { useEffect, useState } from "react";
import type { Job } from "../api/types";

// Returns the latest current-job payload from the SSE stream (null when idle).
export function useEventStream(path: string): Job | null {
  const [current, setCurrent] = useState<Job | null>(null);
  useEffect(() => {
    const es = new EventSource(path, { withCredentials: true });
    const onPayload = (e: MessageEvent) => {
      try {
        const data = e.data ? JSON.parse(e.data) : null;
        setCurrent(data as Job | null);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.addEventListener("status", onPayload);
    es.addEventListener("progress", onPayload);
    es.addEventListener("heartbeat", onPayload);
    return () => es.close();
  }, [path]);
  return current;
}
```

- [ ] **Step 4: Create `web/src/hooks/queries.ts`:**
```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Exclusion, JobPage, LibraryPage, ScanStatus, Status } from "../api/types";

export const useStatus = () =>
  useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/api/status"), refetchInterval: 5000 });

export const useLibrary = (source?: string, eligibility?: string, offset = 0, limit = 100) =>
  useQuery({
    queryKey: ["library", source, eligibility, offset, limit],
    queryFn: () => {
      const p = new URLSearchParams();
      if (source) p.set("source", source);
      if (eligibility) p.set("eligibility", eligibility);
      p.set("offset", String(offset));
      p.set("limit", String(limit));
      return api.get<LibraryPage>(`/api/library?${p.toString()}`);
    },
  });

export const useJobs = (state?: string) =>
  useQuery({
    queryKey: ["jobs", state],
    queryFn: () => api.get<JobPage>(`/api/jobs${state ? `?state_filter=${state}` : ""}`),
    refetchInterval: 5000,
  });

export const useExclusions = () =>
  useQuery({ queryKey: ["exclusions"], queryFn: () => api.get<Exclusion[]>("/api/exclusions") });

export const useScanStatus = () =>
  useQuery({ queryKey: ["scanStatus"], queryFn: () => api.get<ScanStatus>("/api/scan/status"), refetchInterval: 3000 });

export function useAction() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["library"] });
    qc.invalidateQueries({ queryKey: ["status"] });
    qc.invalidateQueries({ queryKey: ["exclusions"] });
  };
  return {
    scan: useMutation({ mutationFn: (b: object) => api.post("/api/scan", b), onSuccess: invalidate }),
    enqueue: useMutation({ mutationFn: (b: object) => api.post("/api/enqueue", b), onSuccess: invalidate }),
    cancel: useMutation({ mutationFn: (id: number) => api.post(`/api/jobs/${id}/cancel`), onSuccess: invalidate }),
    retry: useMutation({ mutationFn: (id: number) => api.post(`/api/jobs/${id}/retry`), onSuccess: invalidate }),
    addExclusion: useMutation({ mutationFn: (b: object) => api.post("/api/exclusions", b), onSuccess: invalidate }),
    delExclusion: useMutation({ mutationFn: (id: number) => api.del(`/api/exclusions/${id}`), onSuccess: invalidate }),
  };
}
```

- [ ] **Step 5: Run, confirm PASS** (`npx vitest run src/hooks/useEventStream.test.ts`). 1 passed.
- [ ] **Step 6: Run all web tests** `npm test`. Expect 4 passed (smoke + client(2) + sse).
- [ ] **Step 7: Commit**
```bash
git add source_code/web/src/hooks
git commit -m "feat: TanStack Query hooks + SSE useEventStream hook"
```

---

## Phase C — Design system

## Task 8: Establish the design system with frontend-design-pro

**Files:** Create `web/src/components/ui/*` (shadcn-style primitives), `web/src/theme.css` (or extend `index.css`), and a short `docs/superpowers/cycle3-design-notes.md`.

> This task is design, not TDD. The CONTROLLER runs the `frontend-design-pro:design` skill (or `frontend-design-pro:design-wizard`) to choose a palette/typography/aesthetic for a "media server admin dashboard, dark, dense data tables, live progress" and to generate the base shadcn/ui primitives the screens will use (button, card, table, badge, dialog, input, progress, tabs/nav, toast). The implementer subagent does NOT invent visuals.

- [ ] **Step 1:** Controller invokes `frontend-design-pro` to produce: a Tailwind theme (colors, fonts, radius, dark mode) applied in `tailwind.config.js`/`index.css`, and the shadcn primitive components under `web/src/components/ui/`.
- [ ] **Step 2:** Record the chosen palette/fonts/aesthetic in `docs/superpowers/cycle3-design-notes.md` so later screen tasks stay consistent.
- [ ] **Step 3:** Add a render smoke test `web/src/components/ui/ui.test.tsx` that renders the Button and Badge primitives and asserts they mount.
- [ ] **Step 4:** `npm test` stays green; `npm run build` still succeeds.
- [ ] **Step 5: Commit**
```bash
git add source_code/web/src/components source_code/web/tailwind.config.js source_code/web/src/index.css docs/superpowers/cycle3-design-notes.md
git commit -m "feat: design system + shadcn primitives (frontend-design-pro)"
```

---

## Phase D — App shell + screens

For each screen task: the implementer builds the component using the Task 8 primitives, wires the Task 6/7 data hooks, and writes a focused RTL test (render with a `QueryClientProvider` and a mocked `fetch`/hooks; assert key elements + one action). Visual polish follows the design notes. Each task ends green (`npm test`) and buildable (`npm run build`), then commits.

## Task 9: App shell, routing, AuthGate, Login

**Files:** `web/src/auth/AuthGate.tsx`, `web/src/pages/Login.tsx`, `web/src/components/Nav.tsx`, rewrite `web/src/App.tsx` + `web/src/main.tsx`; Test: `web/src/auth/AuthGate.test.tsx`

- [ ] **Step 1: Test** `AuthGate.test.tsx`: mock `fetch` so `GET /api/me` returns `{authed:false}` → renders Login (a password input + submit); then `{authed:true}` → renders children (e.g. text "Dashboard"). Assert the login form posts to `/api/login`.
- [ ] **Step 2: Implement.**
  - `main.tsx`: wrap `<App/>` in `QueryClientProvider` + `BrowserRouter`.
  - `AuthGate.tsx`: query `/api/me`; if not authed render `<Login/>`; on `ApiError` 401 from any query (via a global handler or the client) show `<Login/>`. On login success, invalidate and render children.
  - `Login.tsx`: single password field → `api.post('/api/login',{password})` → on success refetch `/api/me`; on 401 show "wrong password".
  - `Nav.tsx`: links to Dashboard/Library/Jobs/Exclusions + a Logout button (`api.post('/api/logout')` then refetch `/api/me`).
  - `App.tsx`: `<AuthGate>` wrapping `<Nav/>` + `<Routes>` for the four pages (placeholders imported from Task 10–13; for THIS task they can be minimal stubs that render their title, replaced by later tasks).
- [ ] **Step 3:** `npm test` green (smoke + client + sse + authgate); `npm run build` ok.
- [ ] **Step 4: Commit** `git commit -m "feat: app shell, routing, auth gate + login"`

## Task 10: Dashboard page

**Files:** `web/src/pages/Dashboard.tsx`; Test: `web/src/pages/Dashboard.test.tsx`
- [ ] Build: worker-alive badge, current-job card with live progress bar (from `useEventStream`), queue length + queued list (from `useStatus`/`useJobs`), library stats, quick actions (Scan dialog → `useAction().scan`, Enqueue → `useAction().enqueue`); scan progress via `useScanStatus`.
- [ ] Test (RTL + mocked hooks/fetch): renders worker status + a current job's progress value; clicking "Enqueue" calls the enqueue endpoint.
- [ ] `npm test` green; build ok; commit `feat: dashboard page`.

## Task 11: Library page

**Files:** `web/src/pages/Library.tsx`; Test: `web/src/pages/Library.test.tsx`
- [ ] Build: server-paginated table (`useLibrary`) with source/eligibility filter controls; per-row Enqueue (when eligibility==="needs_transcode") and Exclude actions; a Scan button (app/scope) → `useAction().scan`; prev/next pagination.
- [ ] Test: renders rows from a mocked library page; changing the eligibility filter refetches with the param; clicking Exclude posts to `/api/exclusions`.
- [ ] `npm test` green; build ok; commit `feat: library page`.

## Task 12: Jobs page

**Files:** `web/src/pages/Jobs.tsx`; Test: `web/src/pages/Jobs.test.tsx`
- [ ] Build: jobs table (`useJobs`) with state badges + progress; row expand/detail (sizes, reduction %, error, output filename); Cancel (queued/running) + Retry (failed/skipped_larger/cancelled) → `useAction()`; optional state filter.
- [ ] Test: renders jobs; clicking Cancel on a queued job calls `/api/jobs/{id}/cancel`; Retry on a failed job calls `/api/jobs/{id}/retry`.
- [ ] `npm test` green; build ok; commit `feat: jobs page`.

## Task 13: Exclusions page

**Files:** `web/src/pages/Exclusions.tsx`; Test: `web/src/pages/Exclusions.test.tsx`
- [ ] Build: list (`useExclusions`) of source/key/reason; add form (source+key) → `useAction().addExclusion`; delete button → `useAction().delExclusion`; note that re-eligibility needs a re-scan.
- [ ] Test: renders exclusions; add posts to `/api/exclusions`; delete calls DELETE.
- [ ] `npm test` green; build ok; commit `feat: exclusions page`.

---

## Phase E — Integration, docs, smoke

## Task 14: Build into dist + backend integration test

**Files:** Test: `source_code/tests/test_spa_build_served.py` (optional, gated on dist existing)
- [ ] **Step 1:** Run `cd source_code/web && npm run build` to produce `web/dist`.
- [ ] **Step 2:** Run the BACKEND suite to confirm the real `web/dist` is served: `cd source_code && .venv/Scripts/python.exe -m pytest tests/test_api_spa.py -q` (the existing tests use a temp dist; this step just confirms a real build exists). Optionally add `tests/test_spa_build_served.py` that skips if `web/dist/index.html` is absent, else asserts `create_app()` serves it at `/`.
- [ ] **Step 3:** Full backend suite green; full web suite green.
- [ ] **Step 4: Commit** any test added: `git commit -m "test: SPA build served by FastAPI (skips if not built)"`

## Task 15: Docs + manual end-to-end smoke (user-run)

**Files:** Modify `CLAUDE.md`
- [ ] **Step 1:** Update CLAUDE.md with a **Web UI** section:
  - Dev: `cd source_code/web && npm install && npm run dev` (UI on :5173, proxies /api) + `python -m transcoder.api` (API on :8765).
  - Prod: `cd source_code/web && npm run build` then `python -m transcoder.api` serves UI+API on :8765.
  - Note `.env` needs `APP_PASSWORD` + `SECRET_KEY`.
- [ ] **Step 2: Commit** `git commit -m "docs: document the Cycle 3 web UI dev/prod flows"`.
- [ ] **Step 3 (USER-RUN):** Set `APP_PASSWORD`/`SECRET_KEY` in `.env`, build the UI, start the server, open `http://<box>:8765`, log in, and verify: Dashboard shows worker status; Library lists items + filters; trigger a Scan and watch status; Jobs list renders; Exclusions add/remove works. (A real transcode needs eligible content + real SFTP creds.)

---

## Self-Review Notes (completed by plan author)

- **Spec coverage:** auth settings (T1), auth router+dep (T2), middleware+protection+fixture login (T3), static/catch-all (T4), Vite scaffold (T5), api client/types (T6), query+SSE hooks (T7), design system via frontend-design-pro (T8), shell/auth/login (T9), four screens (T10–13), build+serve integration (T14), docs+smoke (T15). ✔
- **Auth regression guard:** T3 explicitly updates the `api` fixture to auto-login so all Cycle 2 API tests keep passing; T3's own tests logout to verify 401s. ✔
- **Type consistency:** TS `types.ts` mirrors the pydantic schemas (Job.title, ScanStatus.started_at/finished_at, eligibility/state strings). Hooks use `state_filter` (the jobs API query param), `source`/`eligibility` (library params). ✔
- **Catch-all safety:** registered last; `api/`-prefixed misses return JSON 404 (tested); app boots without `web/dist` (tested). ✔
- **Placeholder scan:** backend + infra steps have complete code. Screen tasks (T10–13) specify data bindings, actions, and acceptance-test assertions rather than full verbatim JSX, because the visual components are generated against the Task 8 design system (frontend-design-pro) — this is intentional for the UI layer, not a placeholder gap. ✔
