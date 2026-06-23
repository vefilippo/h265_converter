import { useEffect, useRef, useState } from "react";
import { usePageTitle } from '../hooks/usePageTitle';
import type { LogLine } from "../api/types";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Card, CardContent } from "../components/ui/card";
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
  usePageTitle("Logs");
  const [lines, setLines] = useState<LogLine[]>([]);
  const [cursor, setCursor] = useState(0);
  const [paused, setPaused] = useState(false);
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("All");
  const [search, setSearch] = useState("");
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

  const displayed = lines.filter((l) => {
    if (levelFilter !== "All" && l.level !== levelFilter) return false;
    if (search.trim() && !l.message.toLowerCase().includes(search.trim().toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="font-display text-2xl">Logs</h1>
        <div className="flex items-center gap-3 flex-wrap">
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search logs…"
            className="h-7 w-48 text-xs"
            aria-label="Search log messages"
          />
          <div className="flex items-center gap-1">
            <span className="text-sm text-muted">Level:</span>
            <div className="flex gap-1">
              {LEVEL_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  onClick={() => setLevelFilter(opt)}
                  aria-pressed={levelFilter === opt}
                  className={cn(
                    "px-2 py-0.5 rounded-full text-xs font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
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
            aria-pressed={paused}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
          >
            {paused ? "Resume" : "Pause"}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div
            ref={scrollRef}
            role="log"
            aria-live="polite"
            aria-label="Activity log"
            className="h-[70vh] overflow-auto rounded-lg bg-elevated p-3 font-mono text-xs"
          >
            {displayed.length === 0 ? (
              <p className="text-muted text-center py-8">No activity yet.</p>
            ) : (
              displayed.map((line) => (
                <div key={line.seq} className="flex gap-2 leading-5">
                  <span className="text-muted shrink-0 whitespace-nowrap">
                    {new Date(line.ts).toLocaleString(undefined, { hour12: false })}
                  </span>
                  <span className={cn("shrink-0 font-semibold w-16", levelClass(line.level))}>
                    {line.level}
                  </span>
                  <span className="text-fg break-all">{line.message}</span>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
