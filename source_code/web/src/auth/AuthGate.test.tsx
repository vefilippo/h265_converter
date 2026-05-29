import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AuthGate } from "./AuthGate";

afterEach(() => vi.restoreAllMocks());

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

test("shows login when unauthenticated", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ authed: false }), { status: 200 })));
  wrap(<AuthGate><div>SECRET CONTENT</div></AuthGate>);
  expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
  expect(screen.queryByText("SECRET CONTENT")).not.toBeInTheDocument();
});

test("shows children when authenticated", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ authed: true }), { status: 200 })));
  wrap(<AuthGate><div>SECRET CONTENT</div></AuthGate>);
  expect(await screen.findByText("SECRET CONTENT")).toBeInTheDocument();
});
