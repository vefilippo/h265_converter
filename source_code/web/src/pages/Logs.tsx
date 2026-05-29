import { useEffect, useRef, useState } from "react";
import type { LogLine } from "../api/types";
import { Button } from "../components/ui/button";
import { cn } from "../lib/cn";
import { useLogs } from "../hooks/queries";

const LEVEL_OPTIONS = ["All", "INFO", "WARNING", "ERROR"] as const;
type LevelFilter = typeof LEVEL_OPTIONS[number];

function levelClass(level: string): string {
  switch (level) {
    case "ERROR": return "text-state-failed";
    case "WARNING": return "text-state-skipped";
    default: return "text-muted";
  }
}

export default function Logs() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [cursor, setCursor] = useState(0);
  const [paused, setPaused] = useState(false);
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("All");
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data } = useLogs(cursor);

  useEffect(() => {
    if (!data || data.lines.length === 0) return;
    setLines((prev) => {
      const existingSeqs = new Set(prev.map((l) => l.seq));
      const newLines = data.lines.filter((l) => !existingSeqs.has(l.seq));
      if (newLines.length === 0) return prev;
      const next = [...prev, ...newLines];
      return next.length > 1000 ? next.slice(next.length - 1000) : next;
    });
    setCursor(data.last_seq);
  }, [data]);

  // Auto-scroll to bottom when new lines arrive, unless paused
  useEffect(() => {
    if (paused) return;
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines, paused]);

  const displayed = levelFilter === "All"
    ? lines
    : lines.filter((l) => l.level === levelFilter);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl">Logs</h1>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <span className="text-sm text-muted">Level:</span>
            <div className="flex gap-1">
              {LEVEL_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  onClick={() => setLevelFilter(opt)}
                  className={cn(
                    "px-2 py-0.5 rounded-full text-xs font-medium transition-colors",
                    levelFilter === opt
                      ? "bg-accent text-accent-fg"
                      : "bg-surface text-muted hover:text-fg"
                  )}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? "Resume" : "Pause"}
          </Button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="h-[70vh] overflow-auto rounded-lg border border-border bg-elevated p-3 font-mono text-xs"
      >
        {displayed.length === 0 ? (
          <p className="text-muted text-center py-8">No activity yet.</p>
        ) : (
          displayed.map((line) => (
            <div key={line.seq} className="flex gap-2 leading-5">
              <span className="text-muted shrink-0 whitespace-nowrap">
                {line.ts.replace("T", " ").replace("Z", "")}
              </span>
              <span className={cn("shrink-0 font-semibold w-16", levelClass(line.level))}>
                {line.level}
              </span>
              <span className="text-fg break-all">{line.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
