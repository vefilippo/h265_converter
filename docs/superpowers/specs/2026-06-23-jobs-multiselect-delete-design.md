# Jobs Multi-Select Delete — Design

**Date:** 2026-06-23
**Status:** Approved

## Goal

Let users select one or multiple jobs in the Jobs page and delete them in a
single action. Deletion removes the `job` rows (history); it is distinct from
Cancel (which stops an active job) and Retry.

## Constraints / Decisions

- **Deletable states:** terminal states only — `done`, `failed`,
  `skipped_larger`, `cancelled`. `queued` and `running` jobs are NOT deletable;
  the user must Cancel them first. This avoids deleting the row of a job the
  worker is actively transcoding.
- **API shape:** one bulk endpoint, `POST /api/jobs/delete`, accepting a list of
  ids. Non-deletable or missing ids are skipped (not errors).
- **Select-all** selects only deletable (terminal) rows; queued/running rows
  have a disabled, unchecked checkbox.

## Backend

`source_code/transcoder/api/`

### Schemas (`schemas.py`)
- `JobDeleteIn`: `ids: list[int]`
- `JobDeleteOut`: `deleted: int`, `skipped: int`

### Endpoint (`routers/jobs.py`)
- `POST /api/jobs/delete` with body `JobDeleteIn`.
- Define `_DELETABLE = {"done", "failed", "skipped_larger", "cancelled"}`.
- For each id: fetch the job. If found and `state in _DELETABLE`, delete it and
  count as `deleted`. Otherwise (missing, or queued/running) count as `skipped`.
- Single `session.commit()` after the loop.
- Return `JobDeleteOut(deleted=..., skipped=...)`.

## Frontend

`source_code/web/src/`

### DataTable (`components/ui/data-table.tsx`)
Add opt-in row selection so Library/Exclusions are unaffected:
- New props:
  - `enableSelection?: boolean`
  - `isRowSelectable?: (row: T) => boolean` (defaults to all selectable)
  - `onSelectionChange?: (selectedRows: T[]) => void`
- When `enableSelection` is set, prepend a checkbox column:
  - Header checkbox toggles selection of all *selectable* rows (indeterminate
    when some-but-not-all selected).
  - Row checkbox disabled when `!isRowSelectable(row)`.
  - Checkbox cell stops click propagation so it doesn't trigger `onRowClick`.
- Use TanStack Table's built-in row-selection model
  (`getRowId`, `enableRowSelection`, `onRowSelectionChange`,
  `getFilteredSelectedRowModel`).

### queries (`hooks/queries.ts`)
- Add `deleteJobs` mutation to `useActions()`:
  `mutationFn: (ids: number[]) => api.post("/api/jobs/delete", { ids })`,
  `onSuccess: invalidate`.

### Jobs page (`pages/Jobs.tsx`)
- Track selected jobs via `onSelectionChange`.
- `isRowSelectable = (job) => terminal state`.
- Bulk action bar (shown only when ≥1 selected), above the table:
  - "N selected"
  - destructive **Delete** button
  - **Clear** button (clears selection)
- **Delete** opens a confirmation `Dialog`: "Delete N job(s)? This removes their
  history." Confirm → `deleteJobs.mutate(ids)` → on success clear selection and
  close dialog.

## Testing (TDD — tests first)

### Backend (`source_code/tests/`, pytest)
- Deletes jobs in each terminal state; rows gone afterward.
- Skips `queued`/`running` jobs (left intact), counted as `skipped`.
- Missing ids counted as `skipped`.
- Returns correct `deleted`/`skipped` counts for a mixed batch.

### Frontend (`web/src/pages/Jobs.test.tsx`, Vitest)
- Select-all checkbox selects only terminal-state rows.
- Bulk action bar appears with correct count when rows selected.
- Confirming delete calls `POST /api/jobs/delete` with the selected ids.
- A `DataTable` selection test for the opt-in checkbox column / disabled rows.

## Out of Scope (YAGNI)

- Deleting queued/running jobs directly.
- Undo / soft-delete.
- Deleting associated media items or exclusions.
