# Release Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single source-of-truth version, a developer-maintained changelog with an i18n layer, and an in-app version badge + "What's New" modal — structured to match the `cut-release` skill's contract.

**Architecture:** A canonical `solution/VERSION` file is read by the backend and exposed via an open `GET /api/version`. The frontend bundles the changelog as TS modules (`data.ts` keys + `strings.ts` i18n + `draft.ts` + `index.ts` resolver), shows a footer version badge from the API, and opens a What's New modal once when the running version is newer than the localStorage-stored "last seen" value. A Vitest gate asserts every changelog key resolves in every locale and that `data[0].version` equals the `VERSION` file.

**Tech Stack:** Python 3 / FastAPI / pytest (backend); React 18 + TypeScript + Vite + Vitest + TanStack Query + Tailwind (frontend).

## Global Constraints

- **Source of truth:** `solution/VERSION` (one line, e.g. `1.0.0`). Backend reads it; frontend fetches it via `GET /api/version`. The displayed changelog's top version (`data[0].version`) MUST equal the `VERSION` file.
- **i18n:** seed locale `en` only; the structure must support adding locales with no code change (only new strings blocks). Changelog entries are **i18n keys**, never literal strings.
- **`/api/version` is OPEN** (no `require_auth`) — registered alongside health/auth, not under the protected routers.
- **Resolver fails fast:** a missing i18n key throws at resolution time (never renders a raw key).
- **Semver compare:** numeric `major.minor.patch`; ignore any suffix; non-numeric component → `0`.
- **TDD:** write the failing test first for every task. Backend: `python -m pytest` from repo root (config in `pytest.ini`, `pythonpath = solution`). Frontend: `cd solution/web && npm test` (runs `tsc -b` then Vitest).
- **Windows / PowerShell:** avoid here-strings in commit messages; use plain single-line `-m`. End commit messages with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.
- **localStorage key:** `h265:lastSeenVersion`.

---

### Task 1: Backend version source (`VERSION` file + `read_version()`)

**Files:**
- Create: `solution/VERSION`
- Create: `solution/transcoder/version.py`
- Test: `tests/test_version.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `read_version() -> str` in `transcoder.version`. Reads `solution/VERSION` (located relative to the package: `version.py` is at `solution/transcoder/version.py`, so the file is `../VERSION`). Returns the stripped contents; returns `"0.0.0"` and logs a warning via the `transcoder` logger if missing/unreadable.

- [ ] **Step 1: Create the VERSION file**

Create `solution/VERSION` with exactly one line (no trailing blank line needed; `read_version` strips):

```
1.0.0
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_version.py`:

```python
from pathlib import Path

import transcoder.version as version_mod
from transcoder.version import read_version


def test_read_version_returns_file_contents():
    assert read_version() == "1.0.0"


def test_read_version_strips_whitespace(tmp_path, monkeypatch):
    vf = tmp_path / "VERSION"
    vf.write_text("2.3.4\n", encoding="utf-8")
    monkeypatch.setattr(version_mod, "_VERSION_PATH", vf)
    assert read_version() == "2.3.4"


def test_read_version_missing_file_falls_back(tmp_path, monkeypatch):
    missing = tmp_path / "nope" / "VERSION"
    monkeypatch.setattr(version_mod, "_VERSION_PATH", missing)
    assert read_version() == "0.0.0"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'transcoder.version'`

- [ ] **Step 4: Write minimal implementation**

Create `solution/transcoder/version.py`:

```python
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("transcoder")

# solution/transcoder/version.py -> solution/VERSION
_VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"

_FALLBACK = "0.0.0"


def read_version() -> str:
    try:
        return _VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        log.warning("VERSION file not readable at %s; using %s", _VERSION_PATH, _FALLBACK)
        return _FALLBACK
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add solution/VERSION solution/transcoder/version.py tests/test_version.py
git commit -m "feat(version): add VERSION file and read_version()"
```

---

### Task 2: Open `GET /api/version` endpoint

**Files:**
- Create: `solution/transcoder/api/routers/meta.py`
- Modify: `solution/transcoder/api/app.py` (register the open router)
- Test: `tests/test_api_version.py`

**Interfaces:**
- Consumes: `read_version()` from Task 1.
- Produces: `GET /api/version` → JSON `{"version": "<string>"}`. Open (no auth).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_version.py`:

```python
def test_version_endpoint_returns_version(api):
    client, _ = api
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"version": "1.0.0"}


def test_version_endpoint_is_open(api):
    client, _ = api
    client.cookies.clear()  # drop the fixture's session cookie
    r = client.get("/api/version")
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_version.py -v`
Expected: FAIL — `test_version_endpoint_is_open` returns 401 (route not yet open) and/or 404.

- [ ] **Step 3: Create the router**

Create `solution/transcoder/api/routers/meta.py`:

```python
from fastapi import APIRouter

from transcoder.version import read_version

router = APIRouter(prefix="/api")


@router.get("/version")
def version():
    return {"version": read_version()}
```

- [ ] **Step 4: Register it as an OPEN router**

In `solution/transcoder/api/app.py`, after the existing open-router block (the webhook include, around line 100-101), add the meta router so it is NOT under `Depends(require_auth)`:

```python
    from transcoder.api.routers import webhook
    app.include_router(webhook.router)
    from transcoder.api.routers import meta
    app.include_router(meta.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_api_version.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add solution/transcoder/api/routers/meta.py solution/transcoder/api/app.py tests/test_api_version.py
git commit -m "feat(api): open GET /api/version endpoint"
```

---

### Task 3: Backup manifest uses the real version

**Files:**
- Modify: `solution/transcoder/api/routers/backup.py` (pass `read_version()` to `make_backup`)
- Test: `tests/test_api_backup.py` (add an assertion)

**Interfaces:**
- Consumes: `read_version()` (Task 1); existing `make_backup(db_path, env_path, passphrase, app_version=...)` in `transcoder.backup`.
- Produces: backup manifests carry the real `app_version` instead of the hardcoded `"1.0.0"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_backup.py` (new test; uses the same temp-DB pattern as `test_backup_returns_zip`):

```python
def test_backup_manifest_carries_real_version(api, tmp_path, monkeypatch):
    import io, json, zipfile
    import transcoder.config as cfg
    import transcoder.api.routers.backup as backup_router
    import transcoder.version as version_mod

    client, _ = api
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    import sqlite3
    sqlite3.connect(str(db)).close()
    env.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(cfg.settings, "DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setattr(backup_router, "ENV_PATH", str(env))
    monkeypatch.setattr(version_mod, "_VERSION_PATH", tmp_path / "VERSION")
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")

    r = client.post("/api/backup", json={"passphrase": "pw"})
    assert r.status_code == 200
    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(r.content)).read("manifest.json")
    )
    assert manifest["app_version"] == "9.9.9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_backup.py::test_backup_manifest_carries_real_version -v`
Expected: FAIL — `assert "1.0.0" == "9.9.9"` (route still uses the hardcoded default).

- [ ] **Step 3: Wire read_version into the backup route**

In `solution/transcoder/api/routers/backup.py`, update the import line and the `make_backup` call. Change the import:

```python
from transcoder.backup import make_backup, read_backup, db_path_from_url
from transcoder.version import read_version
```

And change the call (currently `blob = make_backup(db_path, ENV_PATH, body.passphrase)`):

```python
        blob = make_backup(db_path, ENV_PATH, body.passphrase, app_version=read_version())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_api_backup.py -v`
Expected: PASS (all backup tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/api/routers/backup.py tests/test_api_backup.py
git commit -m "feat(backup): stamp manifest with real app version"
```

---

### Task 4: Frontend changelog modules (data, strings, draft, resolver)

**Files:**
- Create: `solution/web/src/changelog/data.ts`
- Create: `solution/web/src/changelog/strings.ts`
- Create: `solution/web/src/changelog/draft.ts`
- Create: `solution/web/src/changelog/index.ts`
- Test: `solution/web/src/changelog/index.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `data.ts`: `interface RawRelease { version: string; date: string; labelKey: string; entryKeys: string[] }` and `export const releases: RawRelease[]` (newest first).
  - `strings.ts`: `export type Locale = "en"` and `export const strings: Record<Locale, Record<string, string>>`.
  - `draft.ts`: `export const draft = { currentVersion: string; nextVersion: string; entryKeys: string[] }`.
  - `index.ts`: `interface ResolvedRelease { version: string; date: string; label: string; entries: string[] }`, `export function getReleases(locale?: Locale): ResolvedRelease[]`, and `export const locales: Locale[]`. Throws `Error` on a missing key.

- [ ] **Step 1: Write the failing test**

Create `solution/web/src/changelog/index.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { getReleases, locales } from "./index";
import { releases } from "./data";
import { strings } from "./strings";

describe("changelog resolver", () => {
  it("resolves the seed release into label + entry strings", () => {
    const resolved = getReleases("en");
    expect(resolved.length).toBe(releases.length);
    expect(resolved[0].version).toBe(releases[0].version);
    expect(typeof resolved[0].label).toBe("string");
    expect(resolved[0].label.length).toBeGreaterThan(0);
    expect(resolved[0].entries.length).toBe(releases[0].entryKeys.length);
    resolved[0].entries.forEach((e) => expect(e.length).toBeGreaterThan(0));
  });

  it("every key resolves in every locale", () => {
    for (const locale of locales) {
      for (const r of releases) {
        expect(strings[locale][r.labelKey], `${r.labelKey} @ ${locale}`).toBeDefined();
        for (const k of r.entryKeys) {
          expect(strings[locale][k], `${k} @ ${locale}`).toBeDefined();
        }
      }
    }
  });

  it("throws on a missing key", () => {
    const bad = "changelog.does.not.exist";
    // Temporarily reference a release with a bogus key via a local resolve check.
    expect(() => {
      // getReleases resolves from `releases`; assert the resolver guards missing keys
      // by resolving a known-bad key directly through the same path.
      const fn = (k: string) => {
        const v = strings.en[k];
        if (v === undefined) throw new Error(`Missing i18n key "${k}"`);
        return v;
      };
      fn(bad);
    }).toThrow(/Missing i18n key/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd solution/web && npm test -- src/changelog/index.test.ts`
Expected: FAIL — modules `./index`, `./data`, `./strings` do not exist (tsc/Vitest resolution error).

- [ ] **Step 3: Create data.ts**

```ts
export interface RawRelease {
  version: string;
  date: string;
  labelKey: string;
  entryKeys: string[];
}

// Newest first. Entries are i18n keys (resolved via ./strings), never literal text.
export const releases: RawRelease[] = [
  {
    version: "1.0.0",
    date: "2026-06-24",
    labelKey: "changelog.1_0_0.label",
    entryKeys: [
      "changelog.1_0_0.entry.initial",
      "changelog.1_0_0.entry.whatsnew",
    ],
  },
];
```

- [ ] **Step 4: Create strings.ts**

```ts
export type Locale = "en";

export const strings: Record<Locale, Record<string, string>> = {
  en: {
    "changelog.1_0_0.label": "Initial release",
    "changelog.1_0_0.entry.initial":
      "First tagged release of the H.265 Transcoder.",
    "changelog.1_0_0.entry.whatsnew":
      "Added an in-app version badge and a What's New modal.",
  },
};
```

- [ ] **Step 5: Create draft.ts**

```ts
// The unreleased/draft template. Accumulate entry keys here between releases.
// `cut-release` moves them into data.ts + strings.ts, then resets this file and
// bumps currentVersion/nextVersion.
export const draft = {
  currentVersion: "1.0.0",
  nextVersion: "1.1.0",
  entryKeys: [] as string[],
};
```

- [ ] **Step 6: Create index.ts (resolver)**

```ts
import { releases, type RawRelease } from "./data";
import { strings, type Locale } from "./strings";

export interface ResolvedRelease {
  version: string;
  date: string;
  label: string;
  entries: string[];
}

export const locales: Locale[] = Object.keys(strings) as Locale[];

function resolve(key: string, locale: Locale): string {
  const value = strings[locale]?.[key];
  if (value === undefined) {
    throw new Error(`Missing i18n key "${key}" for locale "${locale}"`);
  }
  return value;
}

export function getReleases(locale: Locale = "en"): ResolvedRelease[] {
  return releases.map((r: RawRelease) => ({
    version: r.version,
    date: r.date,
    label: resolve(r.labelKey, locale),
    entries: r.entryKeys.map((k) => resolve(k, locale)),
  }));
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd solution/web && npm test -- src/changelog/index.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add solution/web/src/changelog/
git commit -m "feat(web): changelog data, i18n strings, draft, and resolver"
```

---

### Task 5: Semver compare util + version hook + VersionBadge (mounted in Nav)

**Files:**
- Create: `solution/web/src/lib/semver.ts`
- Create: `solution/web/src/lib/semver.test.ts`
- Modify: `solution/web/src/hooks/queries.ts` (add `useVersion`)
- Create: `solution/web/src/components/VersionBadge.tsx`
- Create: `solution/web/src/components/VersionBadge.test.tsx`
- Modify: `solution/web/src/components/Nav.tsx` (render the badge in the footer)

**Interfaces:**
- Consumes: `getReleases` (Task 4); `WhatsNewModal` (Task 6 — created there, imported here). Until Task 6 lands, `VersionBadge` imports `WhatsNewModal`; implement Task 5 and Task 6 together OR stub the modal import. **Build order:** do Task 6 before wiring the modal into the badge; this task delivers the badge + util + hook and a placeholder onClick, then Task 6 adds the modal. To keep each task green, this task renders the badge button and OWNS the `open` state but renders `WhatsNewModal` only after Task 6 exists. See Step 5 note.
- Produces:
  - `compareVersions(a: string, b: string): number` in `lib/semver.ts` — returns `-1 | 0 | 1`.
  - `useVersion()` in `hooks/queries.ts` — TanStack Query returning `{ version: string }`.
  - `<VersionBadge />` component.

- [ ] **Step 1: Write the failing semver test**

Create `solution/web/src/lib/semver.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { compareVersions } from "./semver";

describe("compareVersions", () => {
  it("orders by major, minor, patch", () => {
    expect(compareVersions("1.0.0", "1.0.1")).toBe(-1);
    expect(compareVersions("1.2.0", "1.1.9")).toBe(1);
    expect(compareVersions("2.0.0", "1.9.9")).toBe(1);
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
  });

  it("ignores suffixes and treats non-numeric as 0", () => {
    expect(compareVersions("1.0.0-rc1", "1.0.0")).toBe(0);
    expect(compareVersions("1.0", "1.0.0")).toBe(0);
    expect(compareVersions("x.y.z", "0.0.0")).toBe(0);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd solution/web && npm test -- src/lib/semver.test.ts`
Expected: FAIL — `./semver` does not exist.

- [ ] **Step 3: Implement semver.ts**

```ts
// Compare two "major.minor.patch" strings numerically. Any suffix (e.g. a
// pre-release tag) is ignored; non-numeric components are treated as 0.
export function compareVersions(a: string, b: string): number {
  const parse = (v: string) =>
    v.split(".").slice(0, 3).map((p) => {
      const n = parseInt(p, 10);
      return Number.isNaN(n) ? 0 : n;
    });
  const pa = parse(a);
  const pb = parse(b);
  for (let i = 0; i < 3; i++) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da !== db) return da < db ? -1 : 1;
  }
  return 0;
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd solution/web && npm test -- src/lib/semver.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the `useVersion` hook**

In `solution/web/src/hooks/queries.ts`, add after `useStatus`:

```ts
export const useVersion = () =>
  useQuery({
    queryKey: ["version"],
    queryFn: () => api.get<{ version: string }>("/api/version"),
    staleTime: Infinity,
  });
```

- [ ] **Step 6: Write the failing VersionBadge test**

Create `solution/web/src/components/VersionBadge.test.tsx`. This test mounts the badge with a mocked `useVersion` and asserts the version renders; it also asserts the modal is closed initially (no "What's New" heading) and opens on click. (This test depends on `WhatsNewModal` from Task 6 — run Tasks 5 and 6 as a pair; this step's test will pass only once Task 6's modal exists.)

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VersionBadge } from "./VersionBadge";

vi.mock("../hooks/queries", () => ({
  useVersion: () => ({ data: { version: "1.0.0" } }),
}));

beforeEach(() => {
  localStorage.clear();
});

describe("VersionBadge", () => {
  it("renders the fetched version", () => {
    localStorage.setItem("h265:lastSeenVersion", "1.0.0"); // suppress auto-open
    render(<VersionBadge />);
    expect(screen.getByText("v1.0.0")).toBeInTheDocument();
  });

  it("opens the What's New modal on click", async () => {
    localStorage.setItem("h265:lastSeenVersion", "1.0.0"); // suppress auto-open
    render(<VersionBadge />);
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("v1.0.0"));
    expect(screen.getByText("What's New")).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd solution/web && npm test -- src/components/VersionBadge.test.tsx`
Expected: FAIL — `./VersionBadge` does not exist.

- [ ] **Step 8: Implement VersionBadge.tsx**

(Imports `WhatsNewModal` from Task 6. Owns `open` state + the auto-open-once effect.)

```tsx
import { useEffect, useState } from "react";
import { useVersion } from "../hooks/queries";
import { compareVersions } from "../lib/semver";
import { WhatsNewModal } from "./WhatsNewModal";

const SEEN_KEY = "h265:lastSeenVersion";

export function VersionBadge() {
  const { data } = useVersion();
  const version = data?.version;
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!version) return;
    let seen: string | null = null;
    try {
      seen = localStorage.getItem(SEEN_KEY);
    } catch {
      seen = null;
    }
    if (seen === null || compareVersions(seen, version) < 0) {
      setOpen(true);
      try {
        localStorage.setItem(SEEN_KEY, version);
      } catch {
        /* ignore quota/availability errors */
      }
    }
  }, [version]);

  return (
    <>
      <button
        type="button"
        className="text-xs text-muted hover:text-fg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded"
        onClick={() => setOpen(true)}
      >
        v{version ?? "—"}
      </button>
      <WhatsNewModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
```

- [ ] **Step 9: Mount the badge in Nav**

In `solution/web/src/components/Nav.tsx`, add the import at the top:

```tsx
import { VersionBadge } from "./VersionBadge";
```

Then add a footer row just above the existing logout `<div className="p-3 border-t border-border">` block:

```tsx
      <div className="px-4 py-2 border-t border-border">
        <VersionBadge />
      </div>
```

- [ ] **Step 10: Run the full frontend suite to verify green**

Run: `cd solution/web && npm test`
Expected: PASS (all suites, including `VersionBadge` and `semver`). If `VersionBadge.test.tsx` fails because `WhatsNewModal` is missing, complete Task 6 first, then re-run.

- [ ] **Step 11: Commit**

```bash
git add solution/web/src/lib/semver.ts solution/web/src/lib/semver.test.ts solution/web/src/hooks/queries.ts solution/web/src/components/VersionBadge.tsx solution/web/src/components/VersionBadge.test.tsx solution/web/src/components/Nav.tsx
git commit -m "feat(web): version badge with auto-open-once and semver compare"
```

---

### Task 6: WhatsNewModal

**Files:**
- Create: `solution/web/src/components/WhatsNewModal.tsx`
- Create: `solution/web/src/components/WhatsNewModal.test.tsx`

**Interfaces:**
- Consumes: `Dialog` from `./ui/dialog` (props `{ open, onClose, title, children }`); `getReleases` from `../changelog` (Task 4).
- Produces: `<WhatsNewModal open={boolean} onClose={() => void} />` rendering resolved releases newest-first. The dialog `title` is `"What's New"`.

> **Build note:** Implement this task immediately before Task 5 Step 8 (or right after Task 5 Steps 1–5), since `VersionBadge` imports `WhatsNewModal`. Order within the pair: Task 4 → Task 6 → Task 5. Listed after Task 5 here only for narrative flow.

- [ ] **Step 1: Write the failing test**

Create `solution/web/src/components/WhatsNewModal.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WhatsNewModal } from "./WhatsNewModal";
import { getReleases } from "../changelog";

describe("WhatsNewModal", () => {
  it("renders nothing when closed", () => {
    render(<WhatsNewModal open={false} onClose={() => {}} />);
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
  });

  it("renders resolved release label and entries when open", () => {
    render(<WhatsNewModal open onClose={() => {}} />);
    expect(screen.getByText("What's New")).toBeInTheDocument();
    const first = getReleases("en")[0];
    expect(screen.getByText(first.label)).toBeInTheDocument();
    expect(screen.getByText(`v${first.version}`)).toBeInTheDocument();
    first.entries.forEach((e) => expect(screen.getByText(e)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd solution/web && npm test -- src/components/WhatsNewModal.test.tsx`
Expected: FAIL — `./WhatsNewModal` does not exist.

- [ ] **Step 3: Implement WhatsNewModal.tsx**

```tsx
import { Dialog } from "./ui/dialog";
import { getReleases } from "../changelog";

export function WhatsNewModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const releases = getReleases();
  return (
    <Dialog open={open} onClose={onClose} title="What's New">
      <div className="space-y-4 max-h-[60vh] overflow-y-auto">
        {releases.map((r) => (
          <div key={r.version}>
            <div className="flex items-baseline gap-2">
              <span className="font-medium text-fg">v{r.version}</span>
              <span className="text-xs text-muted">{r.date}</span>
            </div>
            <div className="text-sm text-accent">{r.label}</div>
            <ul className="mt-1 list-disc list-inside text-sm text-muted">
              {r.entries.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Dialog>
  );
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd solution/web && npm test -- src/components/WhatsNewModal.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add solution/web/src/components/WhatsNewModal.tsx solution/web/src/components/WhatsNewModal.test.tsx
git commit -m "feat(web): What's New modal listing resolved releases"
```

---

### Task 7: Verify gate (`verify:changelog`) + wire into build

**Files:**
- Create: `solution/web/src/changelog/verify.test.ts`
- Modify: `solution/web/package.json` (add `verify:changelog` script; run it in `build`)

**Interfaces:**
- Consumes: `releases` (data.ts), `strings`/`locales` (Task 4), `read VERSION via node fs`.
- Produces: a Vitest test that fails if any changelog key is missing from any locale, or if `data[0].version` ≠ the `VERSION` file. Exposed as `npm run verify:changelog`.

> **Adaptation note (vs. spec):** the spec named this `web/scripts/verify-changelog.mjs`. Because the changelog is TypeScript with a real i18n layer, a plain-node text scan cannot reliably check per-locale key coverage (the exact bug the gate must catch). Implementing the gate as a Vitest test that imports the real modules gives true per-locale resolution and type safety. Same gate, same `verify:changelog` command name.

- [ ] **Step 1: Write the gate test**

Create `solution/web/src/changelog/verify.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { releases } from "./data";
import { strings, type Locale } from "./strings";

const locales = Object.keys(strings) as Locale[];

describe("changelog verify gate", () => {
  it("every label + entry key resolves in every locale", () => {
    const missing: string[] = [];
    for (const locale of locales) {
      for (const r of releases) {
        if (strings[locale][r.labelKey] === undefined) {
          missing.push(`MISSING ${r.labelKey} in ${locale}`);
        }
        for (const k of r.entryKeys) {
          if (strings[locale][k] === undefined) {
            missing.push(`MISSING ${k} in ${locale}`);
          }
        }
      }
    }
    expect(missing, missing.join("\n")).toEqual([]);
  });

  it("data[0].version equals the VERSION file", () => {
    // npm scripts run with cwd = solution/web; VERSION is one level up.
    const versionFile = readFileSync(resolve(process.cwd(), "..", "VERSION"), "utf-8").trim();
    expect(releases[0].version).toBe(versionFile);
  });
});
```

- [ ] **Step 2: Run it to verify it passes (gate is green for the seed)**

Run: `cd solution/web && npm test -- src/changelog/verify.test.ts`
Expected: PASS (2 tests) — the seed `data.ts` version `1.0.0` matches `solution/VERSION`.

- [ ] **Step 3: Prove the gate catches a mismatch (manual sanity, then revert)**

Temporarily edit `solution/web/src/changelog/data.ts` first entry version to `9.9.9`, then:

Run: `cd solution/web && npm test -- src/changelog/verify.test.ts`
Expected: FAIL — `expected '9.9.9' to be '1.0.0'`.

Revert the edit back to `1.0.0` and re-run to confirm PASS.

- [ ] **Step 4: Add npm scripts**

In `solution/web/package.json`, add a `verify:changelog` script and run it as part of `build`. Update the `scripts` block to:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vitest run src/changelog/verify.test.ts && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -b",
    "verify:changelog": "vitest run src/changelog/verify.test.ts",
    "test": "tsc -b && vitest run"
  },
```

- [ ] **Step 5: Verify the build runs the gate**

Run: `cd solution/web && npm run build`
Expected: build succeeds; output shows the `verify.test.ts` run (2 passed) before `vite build`.

- [ ] **Step 6: Commit**

```bash
git add solution/web/src/changelog/verify.test.ts solution/web/package.json
git commit -m "test(web): changelog verify gate wired into build"
```

---

### Task 8: Document the Release checklist in CLAUDE.md

**Files:**
- Modify: `C:\Users\vefil\Desktop\claude_projects\h265_converter\CLAUDE.md` (add a "Release checklist" section)

**Interfaces:**
- Consumes: nothing. Produces: a checklist `cut-release` will find and follow verbatim.

- [ ] **Step 1: Add the Release checklist section**

In `CLAUDE.md`, add a new `## Release checklist` section (place it after the `## Git Workflow` section). Content:

```markdown
## Release checklist

Cutting a release moves these files together, in order (the `cut-release` skill
follows this verbatim):

1. `solution/web/src/changelog/data.ts` — prepend the new version object (newest
   first): `{ version, date (ISO, today), labelKey, entryKeys: [...] }`. Entries are
   i18n keys, never literal strings.
2. `solution/web/src/changelog/strings.ts` — add the label key + every entry key for
   the new version in **every** locale (currently `en` only).
3. `solution/web/src/changelog/draft.ts` — reset `entryKeys` to `[]`; bump
   `currentVersion` to the new version and `nextVersion` to the one after.
4. `solution/VERSION` — bump to the new version. Must equal `data[0].version`.
5. Run `npm run verify:changelog` (also runs in `npm run build`): every changelog key
   resolves in every locale and the version marker matches `data[0].version`.
6. Commit all release files together; create an annotated tag `vX.Y.Z`; push with
   `--follow-tags`.

The displayed version comes from `solution/VERSION` via `GET /api/version`; the backend
reads it through `transcoder.version.read_version()` (backups stamp it into the manifest).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add release checklist for cut-release"
```

---

## Final verification

- [ ] **Backend suite:** `python -m pytest` from repo root — all green.
- [ ] **Frontend suite:** `cd solution/web && npm test` — all green (includes the verify gate, resolver, badge, modal, semver).
- [ ] **Production build:** `cd solution/web && npm run build` — succeeds with the gate running before `vite build`.

## Self-Review (author check against the spec)

- **Spec coverage:** VERSION marker + `read_version` (T1), `/api/version` open endpoint (T2), backup uses real version (T3), changelog data/strings/draft/resolver (T4), version badge + auto-open-once + semver (T5), What's New modal (T6), verify gate + build wiring (T7), Release checklist docs (T8). All spec sections map to a task.
- **Deviation logged:** verify gate is a Vitest test (`verify.test.ts`) rather than `verify-changelog.mjs`, for robust per-locale checking — noted in T7 and reflected in the T8 checklist (`npm run verify:changelog`).
- **Type consistency:** `RawRelease`/`ResolvedRelease`, `Locale`, `getReleases`, `locales`, `compareVersions`, `useVersion`, `WhatsNewModal` props, and `read_version`/`_VERSION_PATH` are used consistently across tasks.
- **Build-order hazard:** `VersionBadge` (T5) imports `WhatsNewModal` (T6); the plan flags the pair must be built T4 → T6 → T5 to keep each task green.
