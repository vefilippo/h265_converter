import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  type ColumnDef,
  type Row,
  type Table as TanstackTable,
  type SortingState,
  type RowSelectionState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Table, TBody, TD, TH, THead, TR } from "./table";
import { cn } from "../../lib/cn";

/** Optional per-column metadata understood by DataTable. */
export interface ColumnMeta {
  /** Extra classes applied to the body `<td>` for this column. */
  tdClassName?: string;
}

interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  /** Initial sort; columns are still user-sortable unless disabled per-column. */
  initialSorting?: SortingState;
  /** Click handler for a whole row (e.g. open a detail dialog). */
  onRowClick?: (row: T) => void;
  /** Extra classes per row, derived from the row's data. */
  rowClassName?: (row: T) => string | undefined;
  /** Stable React key for each row. */
  getRowId?: (row: T) => string;
  /** When set, renders a leading checkbox column for row selection. */
  enableSelection?: boolean;
  /** Which rows may be selected (defaults to all). */
  isRowSelectable?: (row: T) => boolean;
  /** Called with the currently-selected row objects whenever selection changes. */
  onSelectionChange?: (rows: T[]) => void;
}

function ariaSort(dir: false | "asc" | "desc"): "ascending" | "descending" | "none" {
  if (dir === "asc") return "ascending";
  if (dir === "desc") return "descending";
  return "none";
}

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

  // Shift-click range selection: `anchorRef` remembers the last row whose
  // checkbox was clicked; `shiftHeldRef` is set from the click event (which
  // carries `shiftKey`) just before the change handler runs. Both are refs so
  // the selection column can be memoized (a stable column identity is required —
  // recreating it each render makes TanStack remount the cells).
  const anchorRef = useRef<string | null>(null);
  const shiftHeldRef = useRef(false);

  // Reads the live table from the cell render context (never a stale closure).
  const handleRowToggle = useCallback((tbl: TanstackTable<T>, row: Row<T>) => {
    const rows = tbl.getRowModel().rows;
    const anchorId = anchorRef.current;
    const anchorIdx = anchorId ? rows.findIndex((r) => r.id === anchorId) : -1;

    if (shiftHeldRef.current && anchorIdx !== -1 && anchorId !== row.id) {
      const curIdx = rows.findIndex((r) => r.id === row.id);
      const [lo, hi] = anchorIdx < curIdx ? [anchorIdx, curIdx] : [curIdx, anchorIdx];
      // Apply the clicked row's resulting state to every selectable row in the
      // visible range (inclusive); non-selectable rows are left untouched.
      const newValue = !row.getIsSelected();
      tbl.setRowSelection((prev) => {
        const next = { ...prev };
        for (let i = lo; i <= hi; i++) {
          const r = rows[i];
          if (!r.getCanSelect()) continue;
          if (newValue) next[r.id] = true;
          else delete next[r.id];
        }
        return next;
      });
    } else {
      row.toggleSelected();
    }
    anchorRef.current = row.id;
  }, []);

  const selectionColumn = useMemo<ColumnDef<T, unknown>>(
    () => ({
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
      cell: ({ row, table }) => (
        <input
          type="checkbox"
          aria-label="Select row"
          checked={row.getIsSelected()}
          disabled={!row.getCanSelect()}
          onChange={() => handleRowToggle(table, row)}
          // `onClick` fires before `onChange` and carries `shiftKey`; stash it so
          // the change handler can decide whether to do a range selection.
          onClick={(e) => {
            e.stopPropagation();
            shiftHeldRef.current = e.shiftKey;
          }}
        />
      ),
    }),
    [handleRowToggle],
  );

  const allColumns = useMemo(
    () => (enableSelection ? [selectionColumn, ...columns] : columns),
    [enableSelection, selectionColumn, columns],
  );

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

  // Skip the initial mount call when nothing is selected — calling the parent
  // setter with [] on every mount causes an extra re-render with no semantic
  // change. We fire once `rowSelection` has actually changed from its initial {}.
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!onSelectionChange) return;
    if (!mountedRef.current) {
      mountedRef.current = true;
      // Only skip if starting with an empty selection (the common case).
      if (Object.keys(rowSelection).length === 0) return;
    }
    onSelectionChange(table.getSelectedRowModel().rows.map((r) => r.original));
    // `rowSelection` is the reactive state; `table` is recreated each render but its
    // selectedRowModel is fully derived from `rowSelection`, so excluding `table`
    // from deps is safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowSelection, onSelectionChange]);

  return (
    <Table>
      <THead>
        {table.getHeaderGroups().map((hg) => (
          <TR key={hg.id} className="hover:bg-transparent">
            {hg.headers.map((header) => {
              const canSort = header.column.getCanSort();
              const dir = header.column.getIsSorted();
              const content = header.isPlaceholder
                ? null
                : flexRender(header.column.columnDef.header, header.getContext());
              return (
                <TH
                  key={header.id}
                  aria-sort={canSort ? ariaSort(dir) : undefined}
                >
                  {canSort ? (
                    <button
                      type="button"
                      onClick={header.column.getToggleSortingHandler()}
                      className={cn(
                        "group inline-flex items-center gap-1 cursor-pointer font-medium transition-colors",
                        "hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded",
                        dir && "text-fg",
                      )}
                    >
                      {content}
                      {/* aria-sort on the <th> conveys state to screen readers;
                          the glyph is a visual affordance only. A faint ↕ marks
                          sortable-but-unsorted columns so they're discoverable. */}
                      <span
                        aria-hidden="true"
                        className={cn(
                          "text-xs leading-none",
                          dir
                            ? "text-accent"
                            : "text-muted/70 group-hover:text-fg",
                        )}
                      >
                        {dir === "asc" ? "▲" : dir === "desc" ? "▼" : "↕"}
                      </span>
                    </button>
                  ) : (
                    content
                  )}
                </TH>
              );
            })}
          </TR>
        ))}
      </THead>
      <TBody>
        {table.getRowModel().rows.map((row) => (
          <TR
            key={row.id}
            className={cn(onRowClick && "cursor-pointer", rowClassName?.(row.original))}
            onClick={onRowClick ? () => onRowClick(row.original) : undefined}
          >
            {row.getVisibleCells().map((cell) => (
              <TD
                key={cell.id}
                className={(cell.column.columnDef.meta as ColumnMeta | undefined)?.tdClassName}
              >
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TD>
            ))}
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
