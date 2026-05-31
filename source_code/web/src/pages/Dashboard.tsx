import { useState } from "react";
import { Badge, jobStateVariant, jobStateLabel, jobTitle } from "../components/ui/badge";
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

type ScanApp = "all" | "sonarr" | "radarr";
type ScanScope = "all" | "new";

export default function Dashboard() {
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
            <div className="font-display text-lg text-fg">Scan &amp; Transcode</div>
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
              "Scan now"
            )}
          </Button>
        </CardContent>
      </Card>

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
            <span className="text-muted">Idle</span>
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
                      <span className="font-mono text-xs text-muted">
                        {row.eligibility}
                      </span>
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
            <span className="text-muted text-sm">No queued jobs</span>
          )}
        </CardContent>
      </Card>

      {/* Quick actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
        </CardHeader>
        <CardContent>
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
            <label className="block text-sm font-medium text-fg mb-1">
              Scope
            </label>
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
