import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { useEventStream } from "./useEventStream";

const instances: FakeES[] = [];
class FakeES {
  listeners: Record<string, (e: MessageEvent) => void> = {};
  url: string;
  closed = false;
  constructor(url: string) { this.url = url; instances.push(this); }
  addEventListener(type: string, cb: (e: MessageEvent) => void) { this.listeners[type] = cb; }
  close() { this.closed = true; }
  emit(type: string, data: unknown) {
    this.listeners[type]?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

function withClient() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children);
  return { qc, wrapper };
}

afterEach(() => { instances.length = 0; vi.restoreAllMocks(); });

test("parses progress events and cleans up", () => {
  vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);
  const { wrapper } = withClient();
  const { result, unmount } = renderHook(() => useEventStream("/api/stream"), { wrapper });
  act(() => instances[0].emit("progress", { id: 5, progress: 42, title: "X" }));
  expect(result.current?.progress).toBe(42);
  act(() => instances[0].emit("heartbeat", null));
  expect(result.current).toBeNull();
  unmount();
  expect(instances[0].closed).toBe(true);
});

test("invalidates status and jobs when the active job changes", () => {
  vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);
  const { qc, wrapper } = withClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  renderHook(() => useEventStream("/api/stream"), { wrapper });

  // Job starts: null -> id 5 triggers invalidation of both queries.
  act(() => instances[0].emit("status", { id: 5, progress: 10 }));
  expect(spy).toHaveBeenCalledWith({ queryKey: ["status"] });
  expect(spy).toHaveBeenCalledWith({ queryKey: ["jobs"] });

  // Progress on the same job: no id change -> no further invalidation.
  spy.mockClear();
  act(() => instances[0].emit("progress", { id: 5, progress: 80 }));
  expect(spy).not.toHaveBeenCalled();

  // Job finishes: id 5 -> idle triggers another invalidation so the
  // space-saved totals refresh immediately.
  act(() => instances[0].emit("heartbeat", null));
  expect(spy).toHaveBeenCalledWith({ queryKey: ["status"] });
});
