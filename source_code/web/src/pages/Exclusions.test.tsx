import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Exclusions from "./Exclusions";

afterEach(() => vi.restoreAllMocks());

const EXCLUSIONS = [
  { id: 1, source: "sonarr", key: "Show A|1|1", reason: "output_larger" },
  { id: 2, source: "radarr", key: "Movie X", reason: "manual" },
];

function makeFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url.includes("/api/exclusions") && init?.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    if (url.includes("/api/exclusions") && init?.method === "POST") {
      return new Response(
        JSON.stringify({ id: 3, source: "sonarr", key: "New|1|1", reason: "manual" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url.includes("/api/exclusions")) {
      return new Response(JSON.stringify(EXCLUSIONS), {
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

test("renders both exclusion keys", async () => {
  vi.stubGlobal("fetch", makeFetch());
  wrap(<Exclusions />);

  expect(await screen.findByText("Show A|1|1")).toBeInTheDocument();
  expect(await screen.findByText("Movie X")).toBeInTheDocument();
});

test("filling key input and clicking Add triggers POST /api/exclusions", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("fetch", mockFetch);
  wrap(<Exclusions />);

  await screen.findByText("Show A|1|1");

  const keyInput = screen.getByPlaceholderText(/Title/i);
  fireEvent.change(keyInput, { target: { value: "New|1|1" } });

  const addBtn = screen.getByRole("button", { name: /add/i });
  fireEvent.click(addBtn);

  await waitFor(() => {
    const calls = mockFetch.mock.calls;
    const postCall = calls.find((c) => {
      const url = typeof c[0] === "string" ? c[0] : c[0].toString();
      return url.includes("/api/exclusions") && c[1]?.method === "POST";
    });
    expect(postCall).toBeDefined();
  });
});

test("clicking Remove on row 1 triggers DELETE /api/exclusions/1", async () => {
  const mockFetch = makeFetch();
  vi.stubGlobal("fetch", mockFetch);
  wrap(<Exclusions />);

  await screen.findByText("Show A|1|1");

  const rows = screen.getAllByRole("row");
  const showARow = rows.find((r) => r.textContent?.includes("Show A|1|1"));
  expect(showARow).toBeDefined();

  const removeBtn = within(showARow!).getByRole("button", { name: /remove/i });
  fireEvent.click(removeBtn);

  await waitFor(() => {
    const calls = mockFetch.mock.calls;
    const deleteCall = calls.find((c) => {
      const url = typeof c[0] === "string" ? c[0] : c[0].toString();
      return url.includes("/api/exclusions/1") && c[1]?.method === "DELETE";
    });
    expect(deleteCall).toBeDefined();
  });
});
