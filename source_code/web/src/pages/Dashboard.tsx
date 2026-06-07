import { useState } from "react";
import { usePageTitle } from '../hooks/usePageTitle';
import { Badge, jobStateVariant, jobStateLabel, jobTitle, eligibilityVariant } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Dialog } from "../components/ui/dialog";
import { Progress } from "../components/ui/progress";
import { Spinner } from "../components/ui/spinner";
import {
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../components/ui/table";
import { useEventStream } from "../hooks/useEventStream";
import { useActions, useJobs, useScanStatus, useStatus } from "../hooks/queries";
import { formatBytes } from "../lib/formatBytes";
import type { Status } from "../api/types";

type ScanApp = "all" | "sonarr" | "radarr";
type ScanScope = "all" | "new";

const ELIGIBILITY_LABEL: Record<string, string> = {
  needs_transcode: "Needs transcode",
  already_h265: "Already H.265",
  below_1080p: "Below 1080p",
  excluded: "Excluded",
};

export default function Dashboard() {
  usePageTitle("Dashboard");
  const { data: status, isLoading: statusLoading } = useStatus();
  const { data: queuedJobs, isLoading: jobsLoading } = useJobs("queued");
  const { data: scanStatus } = useScanStatus();
  const actions = useActions();

  const liveJob = useEventStream("/api/stream");

  const [scanOpen, setScanOpen] = useState(false);
  const [scanApp, setScanApp] = useState<ScanApp>("all");
  const [scanScope, setScanScope] = useState<ScanScope>("all");

  const currentJob = liveJob ?? status?.current_job ?? null;

  const totalLibraryItems =
    status?.stats?.reduce((sum, row) => sum + row.count, 0) ?? 0;

  function handleScanSubmit() {
    actions.scan.mutate({ app: scanApp, scope: scanScope });
    setScanOpen(false);
  }

  function handleEnqueue() {
    actions.enqueue.mutate({});
  }

  if (statusLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner size="lg" />
      </div>
    );
  }

  const scanning = scanStatus?.state === "running";

  return (
    <div className="space-y-6 p-6">
      <h1 className="font-display text-2xl text-fg">Dashboard</h1>

      {/* Primary CTA: one click discovers new media across Sonarr & Radarr and
          queues every eligible file (scan all → scope new → enqueue eligible). */}
      <Card>
        <CardContent className="pt-6 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <div className="font-display text-lg text-fg">Scan &amp; Enqueue</div>
            <div className="text-sm text-muted mt-0.5">
              Find new media on Sonarr &amp; Radarr and queue all eligible files.
            </div>
          </div>
          <Button
            size="lg"
            onClick={() => actions.run.mutate()}
            disabled={actions.run.isPending || scanning}
          >
            {actions.run.isPending || scanning ? (
              <>
                <Spinner size="sm" className="mr-2" />
                Scanning…
              </>
            ) : (
              "Scan & Enqueue"
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Space saved — the headline "reward" metric: how much disk transcoding
          has reclaimed, in absolute bytes and as a percentage. */}
      <SpaceSavedCard savings={status?.savings} />

      {/* Summary cards row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Worker status */}
        <Card>
          <CardHeader>
            <CardTitle>Worker</CardTitle>
          </CardHeader>
          <CardContent>
            {status?.worker_alive ? (
              <Badge variant="done">online</Badge>
            ) : (
              <Badge variant="failed">offline</Badge>
            )}
          </CardContent>
        </Card>

        {/* Queue length */}
        <Card>
          <CardHeader>
            <CardTitle>Queue</CardTitle>
          </CardHeader>
          <CardContent>
            <span className="font-mono text-2xl text-fg">
              {status?.queue_length ?? 0}
            </span>
            <span className="text-muted text-sm ml-2">items</span>
          </CardContent>
        </Card>

        {/* Total library items */}
        <Card>
          <CardHeader>
            <CardTitle>Library</CardTitle>
          </CardHeader>
          <CardContent>
            <span className="font-mono text-2xl text-fg">{totalLibraryItems}</span>
            <span className="text-muted text-sm ml-2">total items</span>
          </CardContent>
        </Card>
      </div>

      {/* Current job card */}
      <Card>
        <CardHeader>
          <CardTitle>Current Job</CardTitle>
        </CardHeader>
        <CardContent>
          {currentJob ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-fg font-medium truncate mr-4">
                  {jobTitle(currentJob)}
                </span>
                <Badge variant={jobStateVariant(currentJob.phase && currentJob.state === "running" ? currentJob.phase : currentJob.state)}>
                  {jobStateLabel(currentJob)}
                </Badge>
              </div>
              <div className="flex items-center gap-3">
                <Progress value={currentJob.progress} className="flex-1" />
                <span className="font-mono text-sm text-muted w-12 text-right">
                  {currentJob.progress}%
                </span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center py-6 text-center">
              <svg className="h-8 w-8 text-muted mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.82m5.84-2.56a14.953 14.953 0 006.16-12.12A14.953 14.953 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.82m2.56-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7a14.953 14.953 0 01-12.12 6.16 14.953 14.953 0 018.41-9.37m7.957-3.965A9 9 0 0121 12c0 2.41-.945 4.6-2.487 6.218" />
              </svg>
              <p className="text-sm text-muted font-medium">Worker idle</p>
              <p className="text-xs text-muted mt-1">No job is currently running</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Stats breakdown */}
      {status?.stats && status.stats.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Library Stats</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH>Source</TH>
                  <TH>Eligibility</TH>
                  <TH>Count</TH>
                </TR>
              </THead>
              <TBody>
                {status.stats.map((row, i) => (
                  <TR key={i}>
                    <TD className="capitalize">{row.source}</TD>
                    <TD>
                      <Badge variant={eligibilityVariant(row.eligibility)}>
                        {ELIGIBILITY_LABEL[row.eligibility] ?? row.eligibility}
                      </Badge>
                    </TD>
                    <TD>
                      <span className="font-mono">{row.count}</span>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Queued jobs list */}
      <Card>
        <CardHeader>
          <CardTitle>
            Queued Jobs
            {queuedJobs && (
              <span className="font-mono text-sm text-muted ml-2">
                ({queuedJobs.total})
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {jobsLoading ? (
            <div className="flex justify-center py-4">
              <Spinner />
            </div>
          ) : queuedJobs && queuedJobs.items.length > 0 ? (
            <Table>
              <THead>
                <TR>
                  <TH>ID</TH>
                  <TH>Title</TH>
                  <TH>State</TH>
                </TR>
              </THead>
              <TBody>
                {queuedJobs.items.slice(0, 5).map((job) => (
                  <TR key={job.id}>
                    <TD>
                      <span className="font-mono text-muted">#{job.id}</span>
                    </TD>
                    <TD className="truncate max-w-xs">
                      {jobTitle(job)}
                    </TD>
                    <TD>
                      <Badge variant={jobStateVariant(job.state)}>
                        {job.state}
                      </Badge>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : (
            <div className="flex flex-col items-center py-6 text-center">
              <svg className="h-8 w-8 text-muted mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
              </svg>
              <p className="text-sm text-muted font-medium">Queue is empty</p>
              <p className="text-xs text-muted mt-1">
                Use{" "}
                <button
                  onClick={() => actions.run.mutate()}
                  className="text-accent hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent/50 rounded"
                >
                  Scan &amp; Enqueue
                </button>
                {" "}to find and queue eligible media
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Quick actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted mb-3 font-medium">Advanced controls</p>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              onClick={() => setScanOpen(true)}
              disabled={actions.scan.isPending}
              variant="outline"
            >
              {actions.scan.isPending && <Spinner size="sm" className="mr-2" />}
              Scan
            </Button>

            {scanStatus && (
              <span className="text-sm text-muted font-mono">
                Scan: {scanStatus.state}
              </span>
            )}

            <Button
              onClick={handleEnqueue}
              disabled={actions.enqueue.isPending}
            >
              {actions.enqueue.isPending && (
                <Spinner size="sm" className="mr-2" />
              )}
              Enqueue eligible
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Scan dialog */}
      <Dialog
        open={scanOpen}
        onClose={() => setScanOpen(false)}
        title="Start Scan"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-fg mb-1">
              App
            </label>
            <div className="flex gap-2">
              {(["all", "sonarr", "radarr"] as ScanApp[]).map((app) => (
                <button
                  key={app}
                  onClick={() => setScanApp(app)}
                  aria-pressed={scanApp === app}
                  className={`px-3 py-1.5 rounded-md text-sm border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 ${
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
            <label className="block text-sm font-medium text-fg mb-1">
              Scope
            </label>
            <div className="flex gap-2">
              {(["all", "new"] as ScanScope[]).map((scope) => (
                <button
                  key={scope}
                  onClick={() => setScanScope(scope)}
                  aria-pressed={scanScope === scope}
                  className={`px-3 py-1.5 rounded-md text-sm border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 ${
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
            <Button
              onClick={handleScanSubmit}
              disabled={actions.scan.isPending}
            >
              {actions.scan.isPending && (
                <Spinner size="sm" className="mr-2" />
              )}
              Start Scan
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

function SpaceSavedCard({ savings }: { savings?: Status["savings"] }) {
  const filesDone = savings?.files_done ?? 0;

  if (!savings || filesDone === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Space Saved</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center py-4 text-center">
            <p className="text-sm text-muted font-medium">No transcodes completed yet</p>
            <p className="text-xs text-muted mt-1">
              Savings will appear here once the first file finishes transcoding.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Fill = the reclaimed portion of the original size; the remainder is the new
  // (transcoded) size. Clamped so a rare negative-on-aggregate never breaks the bar.
  const pct = Math.min(100, Math.max(0, savings.percent_saved));
  const summary =
    `Saved ${formatBytes(savings.bytes_saved)} ` +
    `(${savings.percent_saved.toFixed(1)}%) across ${filesDone} ` +
    `${filesDone === 1 ? "file" : "files"}; new size ${formatBytes(savings.output_bytes)}.`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Space Saved</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="font-mono text-4xl text-accent tabular-nums">
            {formatBytes(savings.bytes_saved)}
          </span>
          <span className="text-sm text-muted">
            <span className="font-mono tabular-nums">{savings.percent_saved.toFixed(1)}%</span>
            {" smaller · "}
            <span className="font-mono tabular-nums">{filesDone}</span>
            {filesDone === 1 ? " file" : " files"}
          </span>
        </div>

        <div className="space-y-1.5">
          <div
            role="img"
            aria-label={summary}
            className="h-2.5 rounded-full bg-elevated overflow-hidden"
          >
            <div
              className="h-full bg-accent rounded-full transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-muted">
            <span>saved</span>
            <span>
              new size{" "}
              <span className="font-mono tabular-nums text-fg">
                {formatBytes(savings.output_bytes)}
              </span>
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
