import { useState } from "react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
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
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: getRowId ? (row) => getRowId(row) : undefined,
  });

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
