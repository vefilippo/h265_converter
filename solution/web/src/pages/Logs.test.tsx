import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import Logs from "./Logs";

afterEach(() => vi.restoreAllMocks());

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

test("renders log lines from the API", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ lines: [
      { seq: 1, ts: "2026-05-29T10:00:00Z", level: "INFO", message: "Sonarr discovery: 5 items" },
      { seq: 2, ts: "2026-05-29T10:00:01Z", level: "ERROR", message: "boom" },
    ], last_seq: 2 }), { status: 200 })
  ));
  wrap(<Logs />);
  expect(await screen.findByText(/Sonarr discovery: 5 items/)).toBeInTheDocument();
  expect(await screen.findByText(/boom/)).toBeInTheDocument();
});
