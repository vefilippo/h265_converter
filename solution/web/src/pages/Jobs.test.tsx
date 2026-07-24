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

    if (url.includes("/api/jobs/delete")) {
      return new Response(JSON.stringify({ deleted: 1, skipped: 0 }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
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
      return new Response(
        JSON.stringify({
          total: 2,
          items: ITEMS,
          state_counts: { running: 1, failed: 1 },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      );
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

test("filter pills show whole-table counts from state_counts", async () => {
  // The paged mock returns only 1 item per page but state_counts covering all
  // 150 jobs: the pills must reflect the whole table, not the visible page.
  vi.stubGlobal("fetch", makePagedFetch());
  wrap(<Jobs />);
  await screen.findByText(/New Movie/);
  expect(screen.getByRole("button", { name: "All (150)" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Done (150)" })).toBeInTheDocument();
});

// Fetch mock that honours the offset param, simulating a table larger than one
// page: newest job on page 1, oldest on page 2.
function makePagedFetch() {
  const job = (id: number, title: string) => ({
    ...ITEMS[1], id, media_item_id: id, state: "done", title,
  });
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/jobs")) {
      const params = new URL(url, "http://localhost").searchParams;
      const offset = Number(params.get("offset") ?? 0);
      const items = offset === 0 ? [job(150, "New Movie")] : [job(1, "Old Show")];
      return new Response(
        JSON.stringify({ total: 150, items, state_counts: { done: 150 } }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify({}), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  });
}

test("paginates: shows page info and fetches the next page via offset", async () => {
  const fetchMock = makePagedFetch();
  vi.stubGlobal("fetch", fetchMock);
  wrap(<Jobs />);

  // Page 1: the newest job is visible, the old one is not.
  expect(await screen.findByText(/New Movie/)).toBeInTheDocument();
  expect(screen.queryByText(/Old Show/)).not.toBeInTheDocument();
  expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /next/i }));

  // Page 2 was requested with offset=100 and renders the older job.
  expect(await screen.findByText(/Old Show/)).toBeInTheDocument();
  expect(screen.getByText(/page 2 of 2/i)).toBeInTheDocument();
  const paged = fetchMock.mock.calls.some(([u]) =>
    String(u).includes("offset=100"),
  );
  expect(paged).toBe(true);
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

test("bulk-deletes selected terminal jobs", async () => {
  const fetchMock = makeFetch();
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Jobs />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  // wait for rows to render
  await screen.findByText("Movie X");

  // select the failed job (id 2). Row checkboxes have aria-label "Select row";
  // the running job (id 1) checkbox is disabled.
  const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
  const enabled = boxes.filter((b) => !b.disabled && b.getAttribute("aria-label") === "Select row");
  fireEvent.click(enabled[0]);

  // bulk bar Delete button appears (only one Delete button before dialog opens)
  const del = await screen.findByRole("button", { name: /delete/i });
  fireEvent.click(del);

  // confirm in dialog — scope to the dialog element to avoid ambiguity with
  // the bulk-bar Delete button that is still rendered behind the dialog
  const dialog = await screen.findByRole("dialog");
  const confirm = within(dialog).getByRole("button", { name: /^delete$/i });
  fireEvent.click(confirm);

  await waitFor(() => {
    const called = fetchMock.mock.calls.some(
      ([u, init]) =>
        String(u).includes("/api/jobs/delete") &&
        init?.body != null &&
        JSON.parse(init.body as string).ids.includes(2),
    );
    expect(called).toBe(true);
  });
});
