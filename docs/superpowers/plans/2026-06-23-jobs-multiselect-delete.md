# Jobs Multi-Select Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users select one or multiple terminal-state jobs in the Jobs page and delete them in a single bulk action.

**Architecture:** A new `POST /api/jobs/delete` bulk endpoint deletes only terminal-state jobs (skipping queued/running/missing). The frontend adds opt-in row selection to the shared `DataTable`, a bulk action bar on the Jobs page, and a confirmation dialog wired to a `deleteJobs` mutation.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend); React + TypeScript + TanStack Table + TanStack Query + Vitest (frontend); pytest (backend tests).

## Global Constraints

- Deletable states are exactly: `done`, `failed`, `skipped_larger`, `cancelled`. Never delete `queued` or `running` jobs.
- Bulk delete is one endpoint `POST /api/jobs/delete` with body `{ "ids": [int, ...] }`, returning `{ "deleted": int, "skipped": int }`.
- Non-deletable ids and missing ids are skipped, not errors.
- Row selection is opt-in on `DataTable` (`enableSelection`) so Library/Exclusions are unaffected.
- Backend tests: `cd source_code && python -m pytest`. Frontend tests: `cd source_code/web && npm test`.
- Follow existing code style; do not bypass git hooks. Prefer single-line `-m` commit messages (no PowerShell here-strings).

---

### Task 1: Backend bulk-delete endpoint

**Files:**
- Modify: `source_code/transcoder/api/schemas.py` (add `JobDeleteIn`, `JobDeleteOut`)
- Modify: `source_code/transcoder/api/routers/jobs.py` (add `delete_jobs` route + `_DELETABLE`)
- Test: `source_code/tests/test_api_jobs.py` (append tests)

**Interfaces:**
- Consumes: `Job` model, `get_session` dep, existing `api` pytest fixture (returns `(client, Session)`), `_seed_item(Session, **kw)` helper in the test module.
- Produces: route `POST /api/jobs/delete` accepting `{ids: list[int]}` → `{deleted: int, skipped: int}`. Schema classes `JobDeleteIn(ids: list[int])` and `JobDeleteOut(deleted: int, skipped: int)`.

- [ ] **Step 1: Write the failing tests**

Append to `source_code/tests/test_api_jobs.py`:

```python
def test_delete_terminal_jobs(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add_all([
        Job(media_item_id=iid, state="done"),
        Job(media_item_id=iid, state="failed"),
        Job(media_item_id=iid, state="skipped_larger"),
        Job(media_item_id=iid, state="cancelled"),
    ])
    s.commit()
    ids = [j.id for j in s.query(Job).all()]
    s.close()

    r = client.post("/api/jobs/delete", json={"ids": ids})
    assert r.status_code == 200
    assert r.json() == {"deleted": 4, "skipped": 0}

    s = Session()
    assert s.query(Job).count() == 0
    s.close()


def test_delete_skips_active_and_missing(api):
    client, Session = api
    iid = _seed_item(Session)
    s = Session()
    s.add_all([
        Job(media_item_id=iid, state="queued"),
        Job(media_item_id=iid, state="running"),
        Job(media_item_id=iid, state="done"),
    ])
    s.commit()
    by_state = {j.state: j.id for j in s.query(Job).all()}
    s.close()

    # queued + running skipped, done deleted, id 99999 missing -> skipped
    ids = [by_state["queued"], by_state["running"], by_state["done"], 99999]
    r = client.post("/api/jobs/delete", json={"ids": ids})
    assert r.status_code == 200
    assert r.json() == {"deleted": 1, "skipped": 3}

    s = Session()
    remaining = {j.state for j in s.query(Job).all()}
    assert remaining == {"queued", "running"}
    s.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd source_code && python -m pytest tests/test_api_jobs.py -k delete -v`
Expected: FAIL — 404 / route not found (endpoint does not exist yet).

- [ ] **Step 3: Add the schemas**

In `source_code/transcoder/api/schemas.py`, near the other `Job*` classes (after `JobLogOut`), add:

```python
class JobDeleteIn(BaseModel):
    ids: list[int]


class JobDeleteOut(BaseModel):
    deleted: int
    skipped: int
```

- [ ] **Step 4: Add the endpoint**

In `source_code/transcoder/api/routers/jobs.py`:

Update the schema import line to include the new classes:

```python
from transcoder.api.schemas import (
    EnqueueIn, EnqueueOut, JobDeleteIn, JobDeleteOut, JobLogOut, JobOut, JobPage,
)
```

Add the deletable-state set near `_RETRYABLE`:

```python
_DELETABLE = {"done", "failed", "skipped_larger", "cancelled"}
```

Add the route (place it after `list_jobs`, before the `/jobs/{job_id}` route so the static `/jobs/delete` path is matched first):

```python
@router.post("/jobs/delete", response_model=JobDeleteOut)
def delete_jobs(body: JobDeleteIn, session: Session = Depends(get_session)):
    deleted = 0
    skipped = 0
    for job_id in body.ids:
        job = session.get(Job, job_id)
        if job is not None and job.state in _DELETABLE:
            session.delete(job)
            deleted += 1
        else:
            skipped += 1
    session.commit()
    return JobDeleteOut(deleted=deleted, skipped=skipped)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd source_code && python -m pytest tests/test_api_jobs.py -v`
Expected: PASS (new delete tests + existing job tests stay green).

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/api/schemas.py source_code/transcoder/api/routers/jobs.py source_code/tests/test_api_jobs.py
git commit -m "feat(api): add POST /api/jobs/delete bulk delete for terminal jobs"
```

---

### Task 2: DataTable opt-in row selection

**Files:**
- Modify: `source_code/web/src/components/ui/data-table.tsx`
- Test: `source_code/web/src/components/ui/data-table.test.tsx` (create)

**Interfaces:**
- Consumes: `@tanstack/react-table` (`getFilteredRowModel`, row-selection model), existing `Table/THead/TBody/TR/TH/TD` primitives.
- Produces: `DataTable` gains props `enableSelection?: boolean`, `isRowSelectable?: (row: T) => boolean`, `onSelectionChange?: (rows: T[]) => void`. When `enableSelection` is true a leading checkbox column renders; the header checkbox toggles all *selectable* rows; non-selectable rows render a disabled checkbox; checkbox clicks do not trigger `onRowClick`.

- [ ] **Step 1: Write the failing test**

Create `source_code/web/src/components/ui/data-table.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "./data-table";

type Row = { id: number; name: string; locked: boolean };

const COLS: ColumnDef<Row, unknown>[] = [
  { id: "name", header: "Name", accessorKey: "name" },
];

const DATA: Row[] = [
  { id: 1, name: "alpha", locked: false },
  { id: 2, name: "beta", locked: true },
  { id: 3, name: "gamma", locked: false },
];

test("select-all selects only selectable rows", () => {
  const onSelectionChange = vi.fn();
  render(
    <DataTable
      columns={COLS}
      data={DATA}
      getRowId={(r) => String(r.id)}
      enableSelection
      isRowSelectable={(r) => !r.locked}
      onSelectionChange={onSelectionChange}
    />,
  );

  // the locked row's checkbox is disabled
  const boxes = screen.getAllByRole("checkbox");
  // boxes[0] is the header select-all
  const header = boxes[0];
  fireEvent.click(header);

  const last = onSelectionChange.mock.calls.at(-1)?.[0] as Row[];
  expect(last.map((r) => r.id).sort()).toEqual([1, 3]);
});

test("locked row checkbox is disabled", () => {
  render(
    <DataTable
      columns={COLS}
      data={DATA}
      getRowId={(r) => String(r.id)}
      enableSelection
      isRowSelectable={(r) => !r.locked}
    />,
  );
  // 1 header + 3 rows = 4 checkboxes; the beta (locked) one is disabled
  const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
  const disabled = boxes.filter((b) => b.disabled);
  expect(disabled.length).toBe(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code/web && npm test -- data-table`
Expected: FAIL — `enableSelection`/checkboxes not implemented (no checkbox role found).

- [ ] **Step 3: Implement selection in DataTable**

Edit `source_code/web/src/components/ui/data-table.tsx`. Update imports to add the selection/filter models and types:

```tsx
import { useState, useEffect } from "react";
import {
  type ColumnDef,
  type SortingState,
  type RowSelectionState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
```

Extend `DataTableProps<T>` with the new optional props:

```tsx
  /** When set, renders a leading checkbox column for row selection. */
  enableSelection?: boolean;
  /** Which rows may be selected (defaults to all). */
  isRowSelectable?: (row: T) => boolean;
  /** Called with the currently-selected row objects whenever selection changes. */
  onSelectionChange?: (rows: T[]) => void;
```

Update the destructured params and the table setup. Add selection state and a leading column when enabled:

```tsx
export function DataTable<T>({
  columns,
  data,
  initialSorting = [],
  onRowClick,
  rowClassName,
  getRowId,
  enableSelection = false,
  isRowSelectable,
  onSelectionChange,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const selectionColumn: ColumnDef<T, unknown> = {
    id: "__select__",
    enableSorting: false,
    header: ({ table }) => (
      <input
        type="checkbox"
        aria-label="Select all"
        checked={table.getIsAllRowsSelected()}
        ref={(el) => {
          if (el) el.indeterminate = table.getIsSomeRowsSelected();
        }}
        onChange={table.getToggleAllRowsSelectedHandler()}
      />
    ),
    cell: ({ row }) => (
      <input
        type="checkbox"
        aria-label="Select row"
        checked={row.getIsSelected()}
        disabled={!row.getCanSelect()}
        onChange={row.getToggleSelectedHandler()}
        onClick={(e) => e.stopPropagation()}
      />
    ),
  };

  const allColumns = enableSelection ? [selectionColumn, ...columns] : columns;

  const table = useReactTable({
    data,
    columns: allColumns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: enableSelection
      ? (row) => (isRowSelectable ? isRowSelectable(row.original) : true)
      : false,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: getRowId ? (row) => getRowId(row) : undefined,
  });

  useEffect(() => {
    if (!onSelectionChange) return;
    onSelectionChange(table.getSelectedRowModel().rows.map((r) => r.original));
  }, [rowSelection, onSelectionChange, table]);
```

The existing `THead`/`TBody` render logic already iterates `table.getHeaderGroups()` and `table.getRowModel().rows`, so the new column renders automatically. Leave that JSX unchanged.

Note: `table.getToggleAllRowsSelectedHandler()` respects `enableRowSelection`, so select-all only selects rows where `isRowSelectable` is true.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code/web && npm test -- data-table`
Expected: PASS.

- [ ] **Step 5: Run the full frontend suite (guard against regressions)**

Run: `cd source_code/web && npm test`
Expected: PASS — Library/Exclusions tables unaffected (they don't pass `enableSelection`).

- [ ] **Step 6: Commit**

```bash
git add source_code/web/src/components/ui/data-table.tsx source_code/web/src/components/ui/data-table.test.tsx
git commit -m "feat(web): add opt-in row selection to DataTable"
```

---

### Task 3: deleteJobs mutation + Jobs page bulk delete UI

**Files:**
- Modify: `source_code/web/src/hooks/queries.ts` (add `deleteJobs` to `useActions`)
- Modify: `source_code/web/src/pages/Jobs.tsx` (selection state, bulk bar, confirm dialog)
- Test: `source_code/web/src/pages/Jobs.test.tsx` (append tests + extend mock fetch)

**Interfaces:**
- Consumes: `useActions()` from `hooks/queries.ts`; `DataTable` props `enableSelection`/`isRowSelectable`/`onSelectionChange` from Task 2; `Dialog`, `Button` primitives; `api.post` from `api/client.ts`.
- Produces: `useActions().deleteJobs` mutation `(ids: number[]) => api.post("/api/jobs/delete", { ids })`. Jobs page shows a bulk bar when ≥1 job selected and POSTs selected ids to `/api/jobs/delete` on confirm.

- [ ] **Step 1: Write the failing test**

In `source_code/web/src/pages/Jobs.test.tsx`, extend `makeFetch` to capture delete calls. Add this branch inside the `request` function (before the generic `/api/jobs` branch):

```tsx
    if (url.includes("/api/jobs/delete")) {
      return new Response(JSON.stringify({ deleted: 1, skipped: 0 }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
```

Then append a test (the existing tests already show the render+fetch-mock pattern):

```tsx
test("bulk-deletes selected terminal jobs", async () => {
  const fetchMock = makeFetch();
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Jobs />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  // wait for rows to render
  await screen.findByText("Movie X");

  // select the failed job (id 2). Row checkboxes have aria-label "Select row";
  // the running job (id 1) checkbox is disabled.
  const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
  const enabled = boxes.filter((b) => !b.disabled && b.getAttribute("aria-label") === "Select row");
  fireEvent.click(enabled[0]);

  // bulk bar Delete button appears
  const del = await screen.findByRole("button", { name: /delete/i });
  fireEvent.click(del);

  // confirm in dialog
  const confirm = await screen.findByRole("button", { name: /^delete$/i });
  fireEvent.click(confirm);

  await waitFor(() => {
    const called = fetchMock.mock.calls.some(
      ([u, init]) =>
        String(u).includes("/api/jobs/delete") &&
        init?.body != null &&
        JSON.parse(init.body as string).ids.includes(2),
    );
    expect(called).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code/web && npm test -- Jobs`
Expected: FAIL — no row checkboxes / no Delete button (selection UI not wired yet).

- [ ] **Step 3: Add the deleteJobs mutation**

In `source_code/web/src/hooks/queries.ts`, inside the returned object of `useActions()`, add (next to `retry`):

```tsx
    deleteJobs: useMutation({
      mutationFn: (ids: number[]) => api.post("/api/jobs/delete", { ids }),
      onSuccess: invalidate,
    }),
```

- [ ] **Step 4: Wire selection + bulk bar + confirm dialog into Jobs page**

In `source_code/web/src/pages/Jobs.tsx`:

Add state near the other `useState` calls in `Jobs()`:

```tsx
  const [selected, setSelected] = useState<Job[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
```

Add a terminal-state predicate near the top-level helpers (outside the component, beside `jobWhen`):

```tsx
const DELETABLE_STATES = new Set([
  "done",
  "failed",
  "skipped_larger",
  "cancelled",
]);

function isJobDeletable(job: Job): boolean {
  return DELETABLE_STATES.has(job.state);
}
```

Render the bulk action bar between the filter header `</div>` and the loading block (only when something is selected):

```tsx
      {selected.length > 0 && (
        <div className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2">
          <span className="text-sm">{selected.length} selected</span>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setConfirmDelete(true)}
          >
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
            Clear
          </Button>
        </div>
      )}
```

Pass selection props to the `DataTable`:

```tsx
          <DataTable
            columns={columns}
            data={jobs}
            getRowId={(job) => String(job.id)}
            initialSorting={[{ id: "when", desc: true }]}
            onRowClick={(job) => setDetailJob(job)}
            enableSelection
            isRowSelectable={isJobDeletable}
            onSelectionChange={setSelected}
          />
```

Add the confirmation dialog near the `detailJob` dialog at the bottom of the return:

```tsx
      {confirmDelete && (
        <Dialog
          open
          onClose={() => setConfirmDelete(false)}
          title={`Delete ${selected.length} job(s)?`}
        >
          <p className="text-sm text-muted">
            This permanently removes the selected job records and their history.
            It does not affect your media files.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={actions.deleteJobs.isPending}
              onClick={() =>
                actions.deleteJobs.mutate(
                  selected.map((j) => j.id),
                  {
                    onSuccess: () => {
                      setConfirmDelete(false);
                      setSelected([]);
                    },
                  },
                )
              }
            >
              Delete
            </Button>
          </div>
        </Dialog>
      )}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd source_code/web && npm test -- Jobs`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd source_code/web && npm test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add source_code/web/src/hooks/queries.ts source_code/web/src/pages/Jobs.tsx source_code/web/src/pages/Jobs.test.tsx
git commit -m "feat(web): multi-select delete in Jobs page"
```

---

### Task 4: Docs + full-suite verification

**Files:**
- Modify: `CLAUDE.md` (document the new endpoint)

- [ ] **Step 1: Document the endpoint**

In `CLAUDE.md`, in the "Key endpoints" list under **Serve (API, Cycle 2)**, add `POST /api/jobs/delete` near the other `/api/jobs/...` entries, e.g. after the `retry` entry:

```
`POST /api/jobs/delete` (bulk-delete terminal-state jobs by id list),
```

- [ ] **Step 2: Run the full backend + frontend suites**

Run: `cd source_code && python -m pytest`
Expected: PASS.

Run: `cd source_code/web && npm test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document POST /api/jobs/delete bulk delete"
```

---

## Self-Review

- **Spec coverage:** Backend endpoint + schemas (Task 1) ✓; terminal-only deletion & skip semantics (Task 1) ✓; DataTable opt-in selection with select-all of selectable rows + disabled rows (Task 2) ✓; `deleteJobs` mutation (Task 3) ✓; bulk bar + confirm dialog + checkbox click isolation (Task 3) ✓; backend + frontend tests (all tasks) ✓; docs (Task 4) ✓.
- **Placeholder scan:** No TBD/TODO; all code shown inline.
- **Type consistency:** `JobDeleteIn`/`JobDeleteOut` names match across schema/route/tests; `deleteJobs(ids: number[])` matches the `{ ids }` body the endpoint reads; `enableSelection`/`isRowSelectable`/`onSelectionChange` consistent between Task 2 and Task 3; `isJobDeletable`/`DELETABLE_STATES` consistent with backend `_DELETABLE`.
