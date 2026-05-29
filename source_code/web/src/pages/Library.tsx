import { useState } from "react";
import { Badge, eligibilityVariant } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Dialog } from "../components/ui/dialog";
import { Spinner } from "../components/ui/spinner";
import {
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/table";
import { useActions, useLibrary } from "../hooks/queries";
import type { MediaItem } from "../api/types";
import { cn } from "../lib/cn";

type ScanApp = "all" | "sonarr" | "radarr";
type ScanScope = "all" | "new";

const LIMIT = 100;

function exclusionKey(item: MediaItem): string {
  return item.source === "sonarr"
    ? `${item.title}|${item.season}|${item.episode}`
    : item.title;
}

function formatTitle(item: MediaItem): string {
  if (item.source === "sonarr" && item.season != null && item.episode != null) {
    const s = String(item.season).padStart(2, "0");
    const e = String(item.episode).padStart(2, "0");
    return `${item.title} S${s}E${e}`;
  }
  if (item.year != null) {
    return `${item.title} (${item.year})`;
  }
  return item.title;
}

export default function Library() {
  const [source, setSource] = useState<string | undefined>(undefined);
  const [eligibility, setEligibility] = useState<string | undefined>(undefined);
  const [offset, setOffset] = useState(0);

  const [scanOpen, setScanOpen] = useState(false);
  const [scanApp, setScanApp] = useState<ScanApp>("all");
  const [scanScope, setScanScope] = useState<ScanScope>("all");

  const { data, isLoading } = useLibrary(source, eligibility, offset, LIMIT);
  const actions = useActions();

  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  function handleSourceChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setSource(e.target.value === "all" ? undefined : e.target.value);
    setOffset(0);
  }

  function handleEligibilityChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setEligibility(e.target.value === "all" ? undefined : e.target.value);
    setOffset(0);
  }

  function handleScanSubmit() {
    actions.scan.mutate({ app: scanApp, scope: scanScope });
    setScanOpen(false);
  }

  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + LIMIT, total);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="font-display text-2xl text-fg">Library</h1>

        <Button
          variant="outline"
          size="sm"
          onClick={() => setScanOpen(true)}
          disabled={actions.scan.isPending}
        >
          {actions.scan.isPending && <Spinner size="sm" className="mr-2" />}
          Scan
        </Button>
      </div>

      {/* Filter controls */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex items-center gap-2">
          <label className="text-sm text-muted" htmlFor="source-filter">
            Source
          </label>
          <select
            id="source-filter"
            value={source ?? "all"}
            onChange={handleSourceChange}
            className={cn(
              "h-8 rounded-md border border-border bg-bg px-2 text-sm text-fg",
              "focus:outline-none focus:ring-2 focus:ring-accent/50"
            )}
          >
            <option value="all">all</option>
            <option value="sonarr">sonarr</option>
            <option value="radarr">radarr</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-muted" htmlFor="eligibility-filter">
            Eligibility
          </label>
          <select
            id="eligibility-filter"
            value={eligibility ?? "all"}
            onChange={handleEligibilityChange}
            className={cn(
              "h-8 rounded-md border border-border bg-bg px-2 text-sm text-fg",
              "focus:outline-none focus:ring-2 focus:ring-accent/50"
            )}
          >
            <option value="all">all</option>
            <option value="needs_transcode">needs_transcode</option>
            <option value="already_h265">already_h265</option>
            <option value="below_1080p">below_1080p</option>
            <option value="excluded">excluded</option>
          </select>
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-muted">No items</div>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <Table>
            <THead>
              <TR>
                <TH>Title</TH>
                <TH>Source</TH>
                <TH>Resolution</TH>
                <TH>Quality</TH>
                <TH>Eligibility</TH>
                <TH>Actions</TH>
              </TR>
            </THead>
            <TBody>
              {items.map((item) => (
                <TR key={item.id}>
                  <TD className="max-w-xs">
                    <span className="truncate block">{formatTitle(item)}</span>
                  </TD>
                  <TD>
                    <Badge variant="neutral" className="capitalize">
                      {item.source}
                    </Badge>
                  </TD>
                  <TD>
                    <span className="font-mono text-sm">
                      {item.resolution ? `${item.resolution}p` : "—"}
                    </span>
                  </TD>
                  <TD>
                    <span className="text-sm text-muted">{item.quality ?? "—"}</span>
                  </TD>
                  <TD>
                    <Badge variant={eligibilityVariant(item.eligibility)}>
                      {item.eligibility}
                    </Badge>
                  </TD>
                  <TD>
                    <div className="flex gap-2">
                      {item.eligibility === "needs_transcode" && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            actions.enqueue.mutate({ source: item.source })
                          }
                          disabled={actions.enqueue.isPending}
                          title={`Enqueue eligible (${item.source})`}
                        >
                          Enqueue
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          actions.addExclusion.mutate({
                            source: item.source,
                            key: exclusionKey(item),
                          })
                        }
                        disabled={actions.addExclusion.isPending}
                      >
                        Exclude
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between flex-wrap gap-3">
          <span className="text-sm text-muted">
            {rangeStart}–{rangeEnd} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + LIMIT >= total}
              onClick={() => setOffset(offset + LIMIT)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* Scan Dialog */}
      <Dialog open={scanOpen} onClose={() => setScanOpen(false)} title="Start Scan">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-fg mb-1">App</label>
            <div className="flex gap-2">
              {(["all", "sonarr", "radarr"] as ScanApp[]).map((app) => (
                <button
                  key={app}
                  onClick={() => setScanApp(app)}
                  className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                    scanApp === app
                      ? "border-accent bg-accent/15 text-accent"
                      : "border-border text-muted hover:bg-surface"
                  }`}
                >
                  {app}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-fg mb-1">Scope</label>
            <div className="flex gap-2">
              {(["all", "new"] as ScanScope[]).map((scope) => (
                <button
                  key={scope}
                  onClick={() => setScanScope(scope)}
                  className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                    scanScope === scope
                      ? "border-accent bg-accent/15 text-accent"
                      : "border-border text-muted hover:bg-surface"
                  }`}
                >
                  {scope}
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setScanOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleScanSubmit} disabled={actions.scan.isPending}>
              {actions.scan.isPending && <Spinner size="sm" className="mr-2" />}
              Start Scan
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
