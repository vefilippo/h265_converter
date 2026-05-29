import { act, renderHook } from "@testing-library/react";
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

afterEach(() => { instances.length = 0; vi.restoreAllMocks(); });

test("parses progress events and cleans up", () => {
  vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);
  const { result, unmount } = renderHook(() => useEventStream("/api/stream"));
  act(() => instances[0].emit("progress", { id: 5, progress: 42, title: "X" }));
  expect(result.current?.progress).toBe(42);
  act(() => instances[0].emit("heartbeat", null));
  expect(result.current).toBeNull();
  unmount();
  expect(instances[0].closed).toBe(true);
});
