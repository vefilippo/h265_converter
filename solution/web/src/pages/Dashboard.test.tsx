import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Dashboard from "./Dashboard";

// Minimal FakeES so useEventStream doesn't throw
class FakeES {
  constructor() {}
  addEventListener() {}
  close() {}
}

afterEach(() => vi.restoreAllMocks());

function makeFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/status")) {
      return new Response(
        JSON.stringify({
          worker_alive: true,
          current_job: null,
          queue_length: 2,
          stats: [{ source: "sonarr", eligibility: "needs_transcode", count: 3 }],
          savings: {
            bytes_saved: 1363148800,
            original_bytes: 5905580032,
            output_bytes: 4542431232,
            percent_saved: 23.08,
            files_done: 142,
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/jobs")) {
      return new Response(
        JSON.stringify({ total: 0, items: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/scan/status")) {
      return new Response(
        JSON.stringify({ state: "idle", detail: {}, started_at: null, finished_at: null }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/enqueue")) {
      return new Response(
        JSON.stringify({ created: 1 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/scan") && init?.method === "POST") {
      return new Response(
        JSON.stringify({ started: true }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </MemoryRouter>
  );
}

test("renders worker online badge and queue length when worker_alive is true", async () => {
  vi.stubGlobal("EventSource", FakeES);
  vi.stubGlobal("fetch", makeFetch());

  wrap(<Dashboard />);

  // Worker status should show "online"
  expect(await screen.findByText("online")).toBeInTheDocument();

  // Queue length should be visible
  expect(await screen.findByText("2")).toBeInTheDocument();
});

test("renders the space saved stat in absolute and percent terms", async () => {
  vi.stubGlobal("EventSource", FakeES);
  vi.stubGlobal("fetch", makeFetch());

  wrap(<Dashboard />);

  // Absolute saved value (1363148800 bytes -> 1.3 GB) and the percentage.
  expect(await screen.findByText("1.3 GB")).toBeInTheDocument();
  expect(await screen.findByText("23.1%")).toBeInTheDocument();
  expect(await screen.findByText("142")).toBeInTheDocument();
});

function runUrls(mockFetch: ReturnType<typeof makeFetch>) {
  return mockFetch.mock.calls
    .filter((c) => c[1]?.method === "POST")
    .map((c) => (typeof c[0] === "string" ? c[0] : c[0].toString()))
    .filter((u) => u.includes("/api/run"));
}

test("default Scan & Enqueue posts /api/run without scope=all", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("EventSource", FakeES);
  vi.stubGlobal("fetch", mockFetch);

  wrap(<Dashboard />);

  await screen.findByText("online");
  fireEvent.click((await screen.findAllByRole("button", { name: /scan & enqueue/i }))[0]);

  await waitFor(() => {
    const urls = runUrls(mockFetch);
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => !u.includes("scope=all"))).toBe(true);
  });
});

test("checking 'Scan all libraries' confirms, then posts /api/run?scope=all", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("EventSource", FakeES);
  vi.stubGlobal("fetch", mockFetch);

  wrap(<Dashboard />);

  await screen.findByText("online");

  // Tick the full-scan checkbox, then click the CTA -> confirmation appears.
  fireEvent.click(screen.getByRole("checkbox", { name: /full scan/i }));
  fireEvent.click((await screen.findAllByRole("button", { name: /scan & enqueue/i }))[0]);

  // No request yet — it waits for confirmation.
  expect(runUrls(mockFetch)).toHaveLength(0);

  // Confirm the full scan.
  fireEvent.click(await screen.findByRole("button", { name: /start full scan/i }));

  await waitFor(() => {
    expect(runUrls(mockFetch).some((u) => u.includes("scope=all"))).toBe(true);
  });
});
