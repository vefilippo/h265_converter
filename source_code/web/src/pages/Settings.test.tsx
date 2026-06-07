import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Settings from "./Settings";

afterEach(() => vi.restoreAllMocks());

const SETTINGS = {
  scheduler_cron: null, scheduler_run_at_startup: "false",
  sonarr_url: "http://sonarr", sonarr_api_key: "", radarr_url: "http://radarr",
  radarr_api_key: "", sftp_host: "h", sftp_port: "22", sftp_username: "u",
  sftp_password: "", handbrake_cli: "hb", handbrake_preset_1080: "p1",
  handbrake_preset_4k: "p2", scheduler_next_run: null,
  webhook_username: "", webhook_password_set: false,
};

function makeFetch(captured: { body?: string }) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/settings") && (!init || init.method === "GET")) {
      return new Response(JSON.stringify(SETTINGS), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/settings") && init?.method === "PUT") {
      captured.body = init.body as string;
      return new Response(JSON.stringify({ updated: ["webhook_username"] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Settings /></MemoryRouter>
    </QueryClientProvider>,
  );
}

test("shows the webhook URLs", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  expect(await screen.findByText(/\/api\/webhook\/sonarr/)).toBeInTheDocument();
  expect(screen.getByText(/\/api\/webhook\/radarr/)).toBeInTheDocument();
});

test("saving webhook section sends username", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  const userInput = await screen.findByLabelText(/webhook username/i);
  fireEvent.change(userInput, { target: { value: "hookuser" } });
  fireEvent.click(screen.getByRole("button", { name: /save webhook settings/i }));
  await waitFor(() => expect(captured.body).toBeTruthy());
  expect(JSON.parse(captured.body!)).toMatchObject({ webhook_username: "hookuser" });
});
