/**
 * The UI has to name the "superseded" eligibility that engine/reap.py writes.
 *
 * Reaped rows are marked rather than deleted (job rows reference them), and the
 * API hides them from the default listing. Without a filter option there is no
 * way to look at them at all, and without a badge variant / label they render
 * as bare unstyled text.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Dashboard from "./Dashboard";
import Library from "./Library";
import { eligibilityVariant } from "../components/ui/badge";

class FakeES {
  constructor() {}
  addEventListener() {}
  close() {}
}

afterEach(() => vi.restoreAllMocks());

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </MemoryRouter>
  );
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

test("a superseded row is styled, not left as a bare default", () => {
  // "cancelled" is the muted, inert treatment -- a retired row is not an error
  // and must not read like one.
  expect(eligibilityVariant("superseded")).toBe("cancelled");
  expect(eligibilityVariant("superseded")).not.toBe(
    eligibilityVariant("some_unknown_value")
  );
});

function libraryFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/library")) {
      return json({
        total: 1,
        items: [
          {
            id: 1,
            source: "sonarr",
            title: "The Ark",
            season: 3,
            episode: 5,
            year: null,
            resolution: 1080,
            quality: "WEBDL-1080p",
            languages: "ENGLISH",
            codec: null,
            is_h265: false,
            eligibility: "superseded",
            external_id: "35817",
          },
        ],
      });
    }
    return json({});
  });
}

test("the Library eligibility filter offers superseded", async () => {
  vi.stubGlobal("fetch", libraryFetch());
  wrap(<Library />);
  await screen.findByText(/The Ark/);

  const select = screen.getByLabelText(/eligibility/i) as HTMLSelectElement;
  const values = Array.from(select.options).map((o) => o.value);

  expect(values).toContain("superseded");
});

test("choosing superseded refetches the Library with that filter", async () => {
  const mockFetch = libraryFetch();
  vi.stubGlobal("fetch", mockFetch);
  wrap(<Library />);
  await screen.findByText(/The Ark/);

  fireEvent.change(screen.getByLabelText(/eligibility/i), {
    target: { value: "superseded" },
  });

  await waitFor(() => {
    const hit = mockFetch.mock.calls.some((c) => {
      const url = typeof c[0] === "string" ? c[0] : c[0].toString();
      return url.includes("/api/library") && url.includes("eligibility=superseded");
    });
    expect(hit).toBe(true);
  });
});

test("the Dashboard breakdown labels superseded in words", async () => {
  vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/status")) {
        return json({
          worker_alive: true,
          current_job: null,
          queue_length: 0,
          stats: [{ source: "sonarr", eligibility: "superseded", count: 592 }],
          savings: {
            bytes_saved: 0,
            original_bytes: 0,
            output_bytes: 0,
            percent_saved: 0,
            files_done: 0,
          },
        });
      }
      if (url.includes("/api/jobs")) return json({ total: 0, items: [] });
      if (url.includes("/api/scan/status")) {
        return json({ state: "idle", detail: {}, started_at: null, finished_at: null });
      }
      return json({});
    })
  );

  wrap(<Dashboard />);

  expect(await screen.findByText("Superseded")).toBeInTheDocument();
});
