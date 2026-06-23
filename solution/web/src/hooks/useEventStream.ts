import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Job } from "../api/types";

// Latest current-job payload from the SSE stream (null when idle/heartbeat).
// Whenever the active job changes — a job starts, finishes, or switches to the
// next one — the queue, library stats, and space-saved totals have changed too,
// so we invalidate those polled queries to refetch immediately instead of
// waiting for the next interval tick.
export function useEventStream(path: string): Job | null {
  const [current, setCurrent] = useState<Job | null>(null);
  const qc = useQueryClient();
  const lastJobId = useRef<number | null>(null);
  useEffect(() => {
    const es = new EventSource(path, { withCredentials: true });
    const onPayload = (e: MessageEvent) => {
      try {
        const data = e.data ? JSON.parse(e.data) : null;
        const job = data as Job | null;
        const id = job?.id ?? null;
        if (id !== lastJobId.current) {
          lastJobId.current = id;
          qc.invalidateQueries({ queryKey: ["status"] });
          qc.invalidateQueries({ queryKey: ["jobs"] });
        }
        setCurrent(job);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.addEventListener("status", onPayload);
    es.addEventListener("progress", onPayload);
    es.addEventListener("heartbeat", onPayload);
    return () => es.close();
  }, [path, qc]);
  return current;
}
