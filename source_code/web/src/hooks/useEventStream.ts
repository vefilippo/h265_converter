import { useEffect, useState } from "react";
import type { Job } from "../api/types";

// Latest current-job payload from the SSE stream (null when idle/heartbeat).
export function useEventStream(path: string): Job | null {
  const [current, setCurrent] = useState<Job | null>(null);
  useEffect(() => {
    const es = new EventSource(path, { withCredentials: true });
    const onPayload = (e: MessageEvent) => {
      try {
        const data = e.data ? JSON.parse(e.data) : null;
        setCurrent(data as Job | null);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.addEventListener("status", onPayload);
    es.addEventListener("progress", onPayload);
    es.addEventListener("heartbeat", onPayload);
    return () => es.close();
  }, [path]);
  return current;
}
