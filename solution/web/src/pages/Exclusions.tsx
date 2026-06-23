import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { usePageTitle } from '../hooks/usePageTitle';
import { useExclusions, useActions } from "../hooks/queries";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { DataTable } from "../components/ui/data-table";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";
import type { Exclusion } from "../api/types";

function statusRank(ex: Exclusion): number {
  return ex.matched ? 0 : 1;
}

export default function Exclusions() {
  usePageTitle("Exclusions");
  const { data: exclusions, isLoading } = useExclusions();
  const actions = useActions();

  const [source, setSource] = useState<"sonarr" | "radarr">("sonarr");
  const [key, setKey] = useState("");

  // List filter controls (client-side over the fetched list). Sorting is handled
  // by the DataTable; the filtered rows feed it.
  const [filterSource, setFilterSource] = useState<"all" | "sonarr" | "radarr">("all");
  const [filterStatus, setFilterStatus] = useState<"all" | "matched" | "orphaned">("all");
  const [filterKey, setFilterKey] = useState("");

  const addError = actions.addExclusion.error as Error | null;
  const orphanCount = (exclusions ?? []).filter((e) => !e.matched).length;

  const visible = useMemo(() => {
    let rows = exclusions ?? [];
    if (filterSource !== "all") rows = rows.filter((e) => e.source === filterSource);
    if (filterStatus !== "all")
      rows = rows.filter((e) => (filterStatus === "matched" ? e.matched : !e.matched));
    const needle = filterKey.trim().toLowerCase();
    if (needle) rows = rows.filter((e) => e.key.toLowerCase().includes(needle));
    return rows;
  }, [exclusions, filterSource, filterStatus, filterKey]);

  const columns = useMemo<ColumnDef<Exclusion, unknown>[]>(
    () => [
      {
        id: "source",
        header: "Source",
        accessorKey: "source",
        cell: ({ row }) => (
          <Badge variant={row.original.source === "sonarr" ? "accent" : "queued"}>
            {row.original.source}
          </Badge>
        ),
      },
      {
        id: "key",
        header: "Key",
        accessorKey: "key",
        meta: { tdClassName: "font-mono text-xs" },
        cell: ({ row }) => row.original.key,
      },
      {
        id: "reason",
        header: "Reason",
        accessorKey: "reason",
        cell: ({ row }) => (
          <Badge variant={row.original.reason === "output_larger" ? "skipped" : "neutral"}>
            {row.original.reason}
          </Badge>
        ),
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (ex) => statusRank(ex),
        cell: ({ row }) => (
          <Badge variant={row.original.matched ? "done" : "skipped"}>
            {row.original.matched ? "in library" : "orphaned"}
          </Badge>
        ),
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        cell: ({ row }) => (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => actions.delExclusion.mutate(row.original.id)}
            disabled={actions.delExclusion.isPending}
          >
            Remove
          </Button>
        ),
      },
    ],
    [actions],
  );

  function handleAdd() {
    if (!key.trim()) return;
    actions.addExclusion.mutate(
      { source, key: key.trim() },
      {
        onSuccess: () => {
          setKey("");
        },
      }
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl">Exclusions</h1>
        <p className="text-muted text-sm mt-1">
          Excluded items are skipped. Removing an exclusion takes effect on the next scan.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Add Exclusion</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 items-center flex-wrap">
            <select
              value={source}
              onChange={(e) => setSource(e.target.value as "sonarr" | "radarr")}
              aria-label="Source"
              className="h-9 rounded-md border border-border bg-elevated px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option value="sonarr">sonarr</option>
              <option value="radarr">radarr</option>
            </select>
            <div className="flex-1 min-w-48">
              <Input
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={source === "sonarr" ? "Title|Season|Episode" : "Title"}
                className="w-full"
              />
              <p className="text-xs text-muted mt-1">
                {source === "sonarr"
                  ? "Format: Title|Season|Episode (e.g. Breaking Bad|1|1)"
                  : "Format: Title (e.g. Inception)"}
              </p>
            </div>
            <Button
              onClick={handleAdd}
              disabled={actions.addExclusion.isPending || !key.trim()}
            >
              {actions.addExclusion.isPending ? <Spinner size="sm" /> : "Add"}
            </Button>
          </div>
          {addError && (
            <p className="text-state-failed text-sm mt-2">{addError.message}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex items-center justify-between">
          <CardTitle>Exclusion List</CardTitle>
          {orphanCount > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => actions.pruneExclusions.mutate()}
              disabled={actions.pruneExclusions.isPending}
              title="Remove exclusions that no longer match any library item"
            >
              {actions.pruneExclusions.isPending ? (
                <Spinner size="sm" />
              ) : (
                `Remove orphaned (${orphanCount})`
              )}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {/* Filter controls */}
          <div className="flex flex-wrap gap-2 items-center px-6 pt-4 pb-2">
            <select
              value={filterSource}
              onChange={(e) => setFilterSource(e.target.value as typeof filterSource)}
              aria-label="Filter by source"
              className="h-9 rounded-md border border-border bg-elevated px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option value="all">all sources</option>
              <option value="sonarr">sonarr</option>
              <option value="radarr">radarr</option>
            </select>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as typeof filterStatus)}
              aria-label="Filter by status"
              className="h-9 rounded-md border border-border bg-elevated px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option value="all">all statuses</option>
              <option value="matched">in library</option>
              <option value="orphaned">orphaned</option>
            </select>
            <Input
              value={filterKey}
              onChange={(e) => setFilterKey(e.target.value)}
              placeholder="Filter by key…"
              aria-label="Filter by key"
              className="flex-1 min-w-48"
            />
          </div>
          {isLoading ? (
            <div className="flex justify-center p-8">
              <Spinner size="lg" />
            </div>
          ) : !exclusions || exclusions.length === 0 ? (
            <p className="text-muted text-sm p-6 text-center">No exclusions</p>
          ) : visible.length === 0 ? (
            <p className="text-muted text-sm p-6 text-center">No exclusions match the filters</p>
          ) : (
            <DataTable
              columns={columns}
              data={visible}
              getRowId={(ex) => String(ex.id)}
              initialSorting={[{ id: "source", desc: false }]}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
