# Release Infrastructure — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorming) — pending implementation plan

## Goal

Give the app a coordinated, consistent release workflow: a single source-of-truth
version, a developer-maintained changelog, and an i18n layer — and surface it to users
as a version badge plus a "What's New" modal in the web UI. The structure deliberately
matches the `cut-release` skill's contract (changelog data + i18n strings + draft +
version marker) so releases can be cut verbatim by that skill later.

Scope decisions (from brainstorming):
- **Surface:** both developer-facing (changelog file) and user-facing (in-app What's New). 
- **i18n:** full layer, seeded with English (`en`) only; structure ready for more locales.
- **In-app:** footer version badge + a "What's New" modal that auto-opens once when the
  running version is newer than what the user last saw (localStorage).
- **Source of truth:** a canonical `solution/VERSION` file; backend reads it, API exposes
  it, frontend bundles the changelog content.

Non-goals (YAGNI): real second-locale translations; a dedicated nav route for the
changelog; server-side rendering of changelog content; pre-release/build-metadata semver.

## Architecture & File Layout

A canonical `solution/VERSION` file is the single source of truth. The backend reads it,
the API exposes it via `GET /api/version`, and the frontend bundles the changelog content
(TS modules) while fetching the running version from the API.

### New files

| File | Role |
|---|---|
| `solution/VERSION` | One line, e.g. `1.0.0`. The marker `cut-release` bumps. |
| `solution/transcoder/version.py` | `read_version()` — reads `VERSION` relative to the package root; returns `"0.0.0"` and logs a warning if missing/unreadable. |
| `solution/web/src/changelog/data.ts` | Release objects, **newest first**: `{ version, date, labelKey, entryKeys: string[] }`. Keys, never literal strings. |
| `solution/web/src/changelog/strings.ts` | i18n strings: `{ en: { [key]: "text" } }`. One locale now; structure ready for more. |
| `solution/web/src/changelog/draft.ts` | Unreleased template: `currentVersion`, `nextVersion`, accumulating entry keys. Reset on release. |
| `solution/web/src/changelog/index.ts` | Resolver: maps keys → strings for a locale (default `en`), throws on a missing key, exposes resolved `releases`. |
| `solution/web/src/components/VersionBadge.tsx` | Footer/sidebar badge showing the running version; click → opens modal. |
| `solution/web/src/components/WhatsNewModal.tsx` | Lists resolved releases newest-first (uses existing `ui/dialog`). |
| `solution/web/scripts/verify-changelog.mjs` | The `cut-release` verify gate (see below). |

### Modified files

- `solution/transcoder/backup.py` — use `read_version()` instead of the hardcoded
  `app_version="1.0.0"` default.
- API router — add `GET /api/version` to an existing router (e.g. `stream.py`) or a small
  new `meta.py`; route is **open/unauthenticated**.
- Frontend layout — mount `VersionBadge` (sidebar footer; login screen footer may reuse it).
- `CLAUDE.md` — add a **Release checklist** section naming the exact files and the
  `verify:changelog` gate, so `cut-release` finds the contract.

## Data Flow & In-App Behavior

**Version display:** On load the frontend calls `GET /api/version` →
`{ "version": "1.0.0" }` (backend reads `VERSION`). `VersionBadge` renders it. This is the
running/deployed version — authoritative.

**Changelog content** is bundled (no API call): `data.ts` + `strings.ts` are resolved
through `index.ts` into a `releases` array of `{ version, date, label, entries: string[] }`.

**What's New modal:**
- Clicking the badge opens `WhatsNewModal`, listing resolved releases newest-first
  (version, date, label heading, bulleted entries).
- **Auto-open-once:** on load, compare the running version (from `/api/version`) against
  `localStorage["h265:lastSeenVersion"]`. If the running version is newer (or no value
  stored), open the modal once and write the running version back. Closing without an
  update does not change stored state. A numeric `major.minor.patch` compare decides
  "newer". A freshly-deployed backend therefore triggers the modal once per logged-in
  user — the intended "What's New on update" behavior.

**Consistency contract:** `data[0].version` (top of `data.ts`) must equal the `VERSION`
file. The verify gate enforces this so the badge (from `VERSION`) and the bundled
changelog never disagree.

## Error Handling & Edge Cases

- **`VERSION` missing/unreadable:** `read_version()` returns `"0.0.0"`, logs a warning via
  the `transcoder` logger. API and backup keep working; no crash.
- **`/api/version` fails or is slow:** the badge renders a neutral placeholder (`—`) until
  it resolves; no modal auto-open is attempted without a version. The app never blocks.
- **Missing i18n key at runtime:** the `index.ts` resolver throws at module load in
  dev/test (fail-fast; caught by the verify gate and a unit test) — never renders a raw
  key. Production builds have already passed the gate.
- **Malformed `localStorage` value:** treated as "no version seen" → modal opens once,
  value overwritten. No exception surfaces.
- **Semver compare on odd input:** parse `major.minor.patch` numerically, ignore any
  suffix; non-numeric components treated as `0`. Documented simplification for an internal
  tool.
- **Auth:** `/api/version` is open/unauthenticated (just a version string; the login
  footer can show it too).

## Verify Gate

`web/scripts/verify-changelog.mjs`:
1. Imports `data.ts` + `strings.ts`. For every release, asserts each `labelKey` + every
   `entryKey` resolves in **every** locale; prints `MISSING <key> in <locale>`.
2. Asserts `data[0].version` equals the `solution/VERSION` file contents.
3. Exits non-zero on any gap. Wired as npm script `verify:changelog` and run as part of
   `npm run build` so a broken release cannot build.

## Testing (TDD — tests before implementation)

**Backend (pytest):**
- `read_version()` returns the file's contents; returns `"0.0.0"` when the file is absent.
- `GET /api/version` returns `{ "version": <file contents> }`.
- `backup` manifest carries the real version (not the hardcoded `"1.0.0"`).

**Frontend (Vitest):**
- Resolver: every release key resolves in every locale; resolver throws on a deliberately
  missing key.
- `WhatsNewModal` renders resolved label + entry text for a sample release.
- Auto-open-once: opens when running version > stored; stays closed when equal; writes back
  to localStorage.
- `VersionBadge` renders the fetched version.

## Release Checklist (to be added to CLAUDE.md)

Files that move together on every release, in order (per `cut-release`):
1. `solution/web/src/changelog/data.ts` — prepend the new version object (newest first).
2. `solution/web/src/changelog/strings.ts` — add label + entry keys for the new version in
   **every** locale.
3. `solution/web/src/changelog/draft.ts` — reset template; bump `currentVersion` +
   `nextVersion`.
4. `solution/VERSION` — bump to the new version (must equal `data[0].version`).
5. Run `npm run verify:changelog` (also runs in `npm run build`) — every key resolves in
   every locale; version marker matches.
6. Commit all release files together; annotated tag `vX.Y`; push `--follow-tags`.
