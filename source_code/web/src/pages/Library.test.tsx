import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Library from "./Library";

afterEach(() => vi.restoreAllMocks());

const ITEMS = [
  {
    id: 1,
    source: "sonarr",
    title: "Show A",
    season: 1,
    episode: 2,
    resolution: 1080,
    quality: "HDTV-1080p",
    languages: "ENG",
    codec: null,
    is_h265: false,
    eligibility: "needs_transcode",
    external_id: "1",
    year: null,
  },
  {
    id: 2,
    source: "radarr",
    title: "Movie X",
    season: null,
    episode: null,
    year: 2020,
    resolution: 2160,
    quality: "Bluray-2160p",
    languages: "ENG",
    codec: "h264",
    is_h265: false,
    eligibility: "excluded",
    external_id: "2",
  },
];

function makeFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url.includes("/api/library")) {
      return new Response(JSON.stringify({ total: 2, items: ITEMS }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/exclusions") && init?.method === "POST") {
      return new Response(
        JSON.stringify({ id: 9, source: "sonarr", key: "Show A|1|2", reason: "manual" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    // Fallback
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

test("renders both item titles", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Library />);

  expect(await screen.findByText(/Show A/)).toBeInTheDocument();
  expect(await screen.findByText(/Movie X/)).toBeInTheDocument();
});

test("clicking Exclude on row 1 triggers POST to /api/exclusions", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("fetch", mockFetch);
  wrap(<Library />);

  // Wait for rows to appear
  await screen.findByText(/Show A/);

  // Find all Exclude buttons and click the first one (row 1)
  const excludeButtons = await screen.findAllByRole("button", { name: /exclude/i });
  fireEvent.click(excludeButtons[0]);

  await waitFor(() => {
    const calls = mockFetch.mock.calls;
    const exclusionCall = calls.find((c) => {
      const url = typeof c[0] === "string" ? c[0] : c[0].toString();
      return url.includes("/api/exclusions") && c[1]?.method === "POST";
    });
    expect(exclusionCall).toBeDefined();
  });
});
