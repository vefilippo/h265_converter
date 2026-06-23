import { useState, useMemo, useEffect } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { usePageTitle } from '../hooks/usePageTitle';
import { useActions, useJobs, useJobLogs } from "../hooks/queries";
import type { Job } from "../api/types";
import { Badge, jobStateVariant, jobStateLabel, jobTitle } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { DataTable } from "../components/ui/data-table";
import { Dialog } from "../components/ui/dialog";
import { Progress } from "../components/ui/progress";
import { Spinner } from "../components/ui/spinner";
import { cn } from "../lib/cn";

const STATE_OPTIONS = [
  { value: "", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "skipped_larger", label: "Skipped Larger" },
  { value: "cancelled", label: "Cancelled" },
];

function mb(n: number | null | undefined): string {
  if (n == null) return "—";
  return (n / 1048576).toFixed(0) + " MB";
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  // Backend stores naive UTC; append Z (when missing) so the browser renders
  // the value in the user's local time.
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

const DELETABLE_STATES = new Set([
  "done",
  "failed",
  "skipped_larger",
  "cancelled",
]);

function isJobDeletable(job: Job): boolean {
  return DELETABLE_STATES.has(job.state);
}

// The most relevant timestamp: when it finished, else started, else created.
function jobWhen(job: Job): string {
  return fmtTime(job.finished_at ?? job.started_at ?? job.created_at);
}

// Numeric epoch for the same "When" value, used as the sort key.
function jobWhenEpoch(job: Job): number {
  const iso = job.finished_at ?? job.started_at ?? job.created_at;
  if (!iso) return 0;
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  const t = d.getTime();
  return isNaN(t) ? 0 : t;
}

function JobDetailDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const live = job.state === "running";
  const { data: logs } = useJobLogs(job.id, live);
  return (
    <Dialog open onClose={onClose} title={jobTitle(job)}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Original Size</dt>
        <dd className="font-mono">{mb(job.original_size)}</dd>

        <dt className="text-muted">Output Size</dt>
        <dd className="font-mono">{mb(job.output_size)}</dd>

        <dt className="text-muted">Reduction</dt>
        <dd className="font-mono">
          {job.reduction_pct != null ? `${job.reduction_pct.toFixed(1)}%` : "—"}
        </dd>

        <dt className="text-muted">Preset</dt>
        <dd>{job.preset ?? "—"}</dd>

        <dt className="text-muted">Created</dt>
        <dd>{fmtTime(job.created_at)}</dd>

        <dt className="text-muted">Started</dt>
        <dd>{fmtTime(job.started_at)}</dd>

        <dt className="text-muted">Finished</dt>
        <dd>{fmtTime(job.finished_at)}</dd>

        {job.output_filename && (
          <>
            <dt className="text-muted">Output File</dt>
            <dd className="font-mono break-all col-span-1">{job.output_filename}</dd>
          </>
        )}

        {job.error_message && (
          <>
            <dt className="text-muted">Error</dt>
            <dd className="text-state-failed col-span-1 break-all">{job.error_message}</dd>
          </>
        )}
      </dl>
      <div className="mt-4">
        <div className="text-muted text-sm mb-1">Logs</div>
        <pre className="bg-surface rounded-md p-3 text-xs font-mono max-h-64 overflow-auto whitespace-pre-wrap">
          {logs?.log ? logs.log : "No logs yet"}
        </pre>
      </div>
    </Dialog>
  );
}

export default function Jobs() {
  usePageTitle("Jobs");
  const [stateFilter, setStateFilter] = useState("");
  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [selected, setSelected] = useState<Job[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Reset selection when the filter changes: keying the DataTable below on the
  // filter remounts it so its internal checkbox state clears, and this clears
  // the page-level selection array so the bulk bar can't act on now-hidden jobs.
  useEffect(() => setSelected([]), [stateFilter]);

  const { data, isLoading } = useJobs(stateFilter || undefined);
  const { data: allData } = useJobs(undefined); // all jobs for count badges
  const actions = useActions();

  const jobs = data?.items ?? [];

  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    (allData?.items ?? []).forEach(j => {
      counts[j.state] = (counts[j.state] ?? 0) + 1;
    });
    return counts;
  }, [allData]);

  function pillLabel(opt: { value: string; label: string }): string {
    if (opt.value === "") return allData ? `All (${allData.total})` : "All";
    const c = stateCounts[opt.value];
    return c != null ? `${opt.label} (${c})` : opt.label;
  }

  const columns = useMemo<ColumnDef<Job, unknown>[]>(
    () => [
      {
        id: "id",
        header: "Job ID",
        accessorKey: "id",
        cell: ({ row }) => (
          <span className="font-mono text-muted">{row.original.id}</span>
        ),
      },
      {
        id: "title",
        header: "Title",
        accessorFn: (job) => jobTitle(job),
        cell: ({ row }) => jobTitle(row.original),
      },
      {
        id: "state",
        header: "State",
        accessorKey: "state",
        cell: ({ row }) => {
          const job = row.original;
          return (
            <Badge variant={jobStateVariant(job.phase && job.state === "running" ? job.phase : job.state)}>
              {jobStateLabel(job)}
            </Badge>
          );
        },
      },
      {
        id: "progress",
        header: "Progress",
        enableSorting: false,
        cell: ({ row }) => {
          const job = row.original;
          return job.state === "running" ? (
            <div className="flex items-center gap-2 min-w-[100px]">
              <Progress value={job.progress} className="flex-1" />
              <span className="font-mono text-xs text-muted whitespace-nowrap">
                {job.progress}%
              </span>
            </div>
          ) : (
            <span className="text-muted">—</span>
          );
        },
      },
      {
        id: "reduction",
        header: "Reduction",
        accessorFn: (job) => job.reduction_pct ?? null,
        sortUndefined: "last",
        cell: ({ row }) => {
          const job = row.original;
          return job.reduction_pct != null ? (
            <span className={job.reduction_pct > 0 ? "text-accent font-mono" : "text-state-failed font-mono"}>
              {job.reduction_pct.toFixed(1)}%
            </span>
          ) : (
            <span className="text-muted">—</span>
          );
        },
      },
      {
        id: "when",
        header: "When",
        accessorFn: (job) => jobWhenEpoch(job),
        cell: ({ row }) => (
          <span className="text-sm text-muted whitespace-nowrap tabular-nums">
            {jobWhen(row.original)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        cell: ({ row }) => {
          const job = row.original;
          return (
            <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
              {(job.state === "queued" || job.state === "running") && (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => actions.cancel.mutate(job.id)}
                  disabled={actions.cancel.isPending}
                >
                  Cancel
                </Button>
              )}
              {(job.state === "failed" ||
                job.state === "skipped_larger" ||
                job.state === "cancelled") && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => actions.retry.mutate(job.id)}
                  disabled={actions.retry.isPending}
                >
                  Retry
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setDetailJob(job)}>
                Details
              </Button>
            </div>
          );
        },
      },
    ],
    [actions],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl">Jobs</h1>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">Filter:</span>
          <div className="flex gap-1 flex-wrap">
            {STATE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setStateFilter(opt.value)}
                aria-pressed={stateFilter === opt.value}
                className={cn(
                  "px-2 py-0.5 rounded-full text-xs font-medium transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
                  stateFilter === opt.value
                    ? "bg-accent text-accent-fg"
                    : "bg-surface text-muted hover:text-fg"
                )}
              >
                {pillLabel(opt)}
              </button>
            ))}
          </div>
        </div>
      </div>

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

      {isLoading && (
        <div className="flex justify-center py-8">
          <Spinner size="lg" />
        </div>
      )}

      {!isLoading && jobs.length === 0 && (
        <p className="text-muted text-sm py-8 text-center">No jobs</p>
      )}

      {!isLoading && jobs.length > 0 && (
        <div className="rounded-lg border border-border overflow-hidden">
          <DataTable
            key={stateFilter}
            columns={columns}
            data={jobs}
            getRowId={(job) => String(job.id)}
            initialSorting={[{ id: "when", desc: true }]}
            onRowClick={(job) => setDetailJob(job)}
            enableSelection
            isRowSelectable={isJobDeletable}
            onSelectionChange={setSelected}
          />
        </div>
      )}

      {detailJob && (
        <JobDetailDialog job={detailJob} onClose={() => setDetailJob(null)} />
      )}

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
    </div>
  );
}
