import { useMemo, useState } from "react";
import { useExclusions, useActions } from "../hooks/queries";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";
import { Table, THead, TBody, TR, TH, TD } from "../components/ui/table";
import type { Exclusion } from "../api/types";

type SortCol = "source" | "key" | "reason" | "status";
type SortDir = "asc" | "desc";

function statusRank(ex: Exclusion): number {
  return ex.matched ? 0 : 1;
}

export default function Exclusions() {
  const { data: exclusions, isLoading } = useExclusions();
  const actions = useActions();

  const [source, setSource] = useState<"sonarr" | "radarr">("sonarr");
  const [key, setKey] = useState("");

  // List filter/sort controls (client-side over the fetched list).
  const [filterSource, setFilterSource] = useState<"all" | "sonarr" | "radarr">("all");
  const [filterStatus, setFilterStatus] = useState<"all" | "matched" | "orphaned">("all");
  const [filterKey, setFilterKey] = useState("");
  const [sortCol, setSortCol] = useState<SortCol>("source");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const addError = actions.addExclusion.error as Error | null;
  const orphanCount = (exclusions ?? []).filter((e) => !e.matched).length;

  const visible = useMemo(() => {
    let rows = exclusions ?? [];
    if (filterSource !== "all") rows = rows.filter((e) => e.source === filterSource);
    if (filterStatus !== "all")
      rows = rows.filter((e) => (filterStatus === "matched" ? e.matched : !e.matched));
    const needle = filterKey.trim().toLowerCase();
    if (needle) rows = rows.filter((e) => e.key.toLowerCase().includes(needle));

    const dir = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortCol === "status") cmp = statusRank(a) - statusRank(b);
      else cmp = String(a[sortCol]).localeCompare(String(b[sortCol]));
      return cmp !== 0 ? cmp * dir : (a.id - b.id);
    });
  }, [exclusions, filterSource, filterStatus, filterKey, sortCol, sortDir]);

  function toggleSort(col: SortCol) {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  }

  function sortArrow(col: SortCol): string {
    if (sortCol !== col) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

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
              className="h-9 rounded-md border border-border bg-elevated px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50"
            >
              <option value="sonarr">sonarr</option>
              <option value="radarr">radarr</option>
            </select>
            <Input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={source === "sonarr" ? "Title|Season|Episode" : "Title"}
              className="flex-1 min-w-48"
            />
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
            <Table>
              <THead>
                <TR>
                  <TH>
                    <button className="hover:text-fg" onClick={() => toggleSort("source")}>
                      Source{sortArrow("source")}
                    </button>
                  </TH>
                  <TH>
                    <button className="hover:text-fg" onClick={() => toggleSort("key")}>
                      Key{sortArrow("key")}
                    </button>
                  </TH>
                  <TH>
                    <button className="hover:text-fg" onClick={() => toggleSort("reason")}>
                      Reason{sortArrow("reason")}
                    </button>
                  </TH>
                  <TH>
                    <button className="hover:text-fg" onClick={() => toggleSort("status")}>
                      Status{sortArrow("status")}
                    </button>
                  </TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {visible.map((ex) => (
                  <TR key={ex.id}>
                    <TD>
                      <Badge variant={ex.source === "sonarr" ? "accent" : "queued"}>
                        {ex.source}
                      </Badge>
                    </TD>
                    <TD className="font-mono text-xs">{ex.key}</TD>
                    <TD>
                      <Badge variant={ex.reason === "output_larger" ? "skipped" : "neutral"}>
                        {ex.reason}
                      </Badge>
                    </TD>
                    <TD>
                      <Badge variant={ex.matched ? "done" : "skipped"}>
                        {ex.matched ? "in library" : "orphaned"}
                      </Badge>
                    </TD>
                    <TD>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => actions.delExclusion.mutate(ex.id)}
                        disabled={actions.delExclusion.isPending}
                      >
                        Remove
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
