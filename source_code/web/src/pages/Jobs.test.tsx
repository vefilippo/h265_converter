import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Jobs from "./Jobs";

afterEach(() => vi.restoreAllMocks());

const ITEMS = [
  {
    id: 1, media_item_id: 1, state: "running", phase: "transcoding", progress: 42,
    preset: null, original_size: null, output_size: null, reduction_pct: null,
    output_filename: null, error_message: null, title: "Show A",
    season: 1, episode: 5,
    created_at: "2026-05-30T09:00:00", started_at: null, finished_at: null,
  },
  {
    id: 2, media_item_id: 2, state: "failed", phase: null, progress: 0,
    preset: "H.265 NVENC 1080p", original_size: 1000000, output_size: null,
    reduction_pct: null, output_filename: null, error_message: "boom",
    title: "Movie X", season: null, episode: null,
    created_at: "2026-05-30T08:00:00", started_at: "2026-05-30T08:01:00",
    finished_at: "2026-05-30T10:30:00",
  },
];

function makeFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url.includes("/api/jobs/1/cancel")) {
      return new Response(JSON.stringify(ITEMS[0]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/jobs/2/retry")) {
      return new Response(JSON.stringify(ITEMS[1]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (/\/api\/jobs\/\d+\/logs/.test(url)) {
      return new Response(JSON.stringify({ log: "hello log" }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/jobs")) {
      return new Response(JSON.stringify({ total: 2, items: ITEMS }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
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

test("renders both job titles", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);

  expect(await screen.findByText(/Show A/)).toBeInTheDocument();
  expect(await screen.findByText(/Movie X/)).toBeInTheDocument();
});

test("TV show job renders S01E05 label", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  expect(await screen.findByText(/Show A — S01E05/)).toBeInTheDocument();
});

test("movie job renders plain title without episode", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  await screen.findByText(/Movie X/);
  const rows = screen.getAllByRole("row");
  const movieRow = rows.find((r) => r.textContent?.includes("Movie X"));
  expect(movieRow).toBeDefined();
  expect(within(movieRow!).queryByText(/S\d\dE\d\d/)).not.toBeInTheDocument();
});

test("shows the job timestamp in the When column", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);

  await screen.findByText(/Movie X/);

  const rows = screen.getAllByRole("row");
  const movieRow = rows.find((r) => r.textContent?.includes("Movie X"));
  // Failed job: When shows the finished time, rendered in the browser locale.
  const finished = new Date("2026-05-30T10:30:00Z").toLocaleString();
  expect(within(movieRow!).getByText(finished)).toBeInTheDocument();

  // Queued job (no started/finished): falls back to created_at.
  const showRow = rows.find((r) => r.textContent?.includes("Show A"));
  const created = new Date("2026-05-30T09:00:00Z").toLocaleString();
  expect(within(showRow!).getByText(created)).toBeInTheDocument();
});

test("defaults to sorting by When descending (most recent first)", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);

  await screen.findByText(/Movie X/);

  // Movie X's When = finished_at 10:30; Show A's When = created_at 09:00.
  // Descending by When puts Movie X (more recent) in the first body row.
  const rows = screen.getAllByRole("row");
  // rows[0] is the header row; rows[1] is the first data row.
  const firstDataRow = rows[1];
  expect(firstDataRow.textContent).toContain("Movie X");
  expect(firstDataRow.textContent).not.toContain("Show A");
});

test("clicking Cancel on queued job triggers POST /api/jobs/1/cancel", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("fetch", mockFetch);
  wrap(<Jobs />);

  await screen.findByText(/Show A/);

  const rows = screen.getAllByRole("row");
  const showARow = rows.find((r) => r.textContent?.includes("Show A"));
  expect(showARow).toBeDefined();

  const cancelBtn = within(showARow!).getByRole("button", { name: /cancel/i });
  fireEvent.click(cancelBtn);

  await waitFor(() => {
    const calls = mockFetch.mock.calls;
    const cancelCall = calls.find((c) => {
      const url = typeof c[0] === "string" ? c[0] : c[0].toString();
      return url.includes("/api/jobs/1/cancel") && c[1]?.method === "POST";
    });
    expect(cancelCall).toBeDefined();
  });
});

test("clicking Retry on failed job triggers POST /api/jobs/2/retry", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("fetch", mockFetch);
  wrap(<Jobs />);

  await screen.findByText(/Movie X/);

  const rows = screen.getAllByRole("row");
  const movieRow = rows.find((r) => r.textContent?.includes("Movie X"));
  expect(movieRow).toBeDefined();

  const retryBtn = within(movieRow!).getByRole("button", { name: /retry/i });
  fireEvent.click(retryBtn);

  await waitFor(() => {
    const calls = mockFetch.mock.calls;
    const retryCall = calls.find((c) => {
      const url = typeof c[0] === "string" ? c[0] : c[0].toString();
      return url.includes("/api/jobs/2/retry") && c[1]?.method === "POST";
    });
    expect(retryCall).toBeDefined();
  });
});

test("running job shows the phase label", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  expect(await screen.findByText("Transcoding")).toBeInTheDocument();
});

test("opening details shows the job log", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Jobs />);
  await screen.findByText(/Movie X/);
  const rows = screen.getAllByRole("row");
  const movieRow = rows.find((r) => r.textContent?.includes("Movie X"));
  fireEvent.click(within(movieRow!).getByRole("button", { name: /details/i }));
  expect(await screen.findByText("hello log")).toBeInTheDocument();
});
