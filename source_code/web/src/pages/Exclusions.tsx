import { useState } from "react";
import { useExclusions, useActions } from "../hooks/queries";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Spinner } from "../components/ui/spinner";
import { Table, THead, TBody, TR, TH, TD } from "../components/ui/table";

export default function Exclusions() {
  const { data: exclusions, isLoading } = useExclusions();
  const actions = useActions();

  const [source, setSource] = useState<"sonarr" | "radarr">("sonarr");
  const [key, setKey] = useState("");

  const addError = actions.addExclusion.error as Error | null;
  const orphanCount = (exclusions ?? []).filter((e) => !e.matched).length;

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
          {isLoading ? (
            <div className="flex justify-center p-8">
              <Spinner size="lg" />
            </div>
          ) : !exclusions || exclusions.length === 0 ? (
            <p className="text-muted text-sm p-6 text-center">No exclusions</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Source</TH>
                  <TH>Key</TH>
                  <TH>Reason</TH>
                  <TH>Status</TH>
                  <TH>Actions</TH>
                </TR>
              </THead>
              <TBody>
                {exclusions.map((ex) => (
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
