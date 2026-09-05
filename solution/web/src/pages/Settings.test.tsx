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
  encoder_family: "cpu", encoder_fallback_cpu: "false",
};

const ENCODER_FAMILIES = [
  { id: "vcn", label: "AMD VCN", preset_1080: "H.265 VCN 1080p", preset_4k: "H.265 VCN 2160p 4K", hardware: true, available: true },
  { id: "nvenc", label: "NVIDIA NVENC", preset_1080: "H.265 NVENC 1080p", preset_4k: "H.265 NVENC 2160p 4K", hardware: true, available: false },
  { id: "qsv", label: "Intel QSV", preset_1080: "H.265 QSV 1080p", preset_4k: "H.265 QSV 2160p 4K", hardware: true, available: false },
  { id: "cpu", label: "CPU (x265)", preset_1080: "H.265 MKV 1080p30", preset_4k: "H.265 MKV 2160p60 4K", hardware: false, available: true },
];

function makeFetch(captured: { body?: string }) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/encoders/detect")) {
      return new Response(JSON.stringify({
        ok: true, available: ["cpu", "vcn"], detected_at: "2026-09-05T17:00:00Z",
        families: ENCODER_FAMILIES,
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/api/encoders")) {
      return new Response(JSON.stringify({
        available: [], detected_at: null,
        families: ENCODER_FAMILIES.map(f => ({ ...f, available: false })),
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
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

test("does not send webhook password when untouched", async () => {
  const SETTINGS_WITH_PW_SET = { ...SETTINGS, webhook_password_set: true };
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/settings") && (!init || init.method === "GET")) {
      return new Response(JSON.stringify(SETTINGS_WITH_PW_SET), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    return makeFetch(captured)(input, init);
  }));
  renderPage();
  const userInput = await screen.findByLabelText(/webhook username/i);
  fireEvent.change(userInput, { target: { value: "hookuser" } });
  fireEvent.click(screen.getByRole("button", { name: /save webhook settings/i }));
  await waitFor(() => expect(captured.body).toBeTruthy());
  expect(JSON.parse(captured.body!)).not.toHaveProperty("webhook_password");
});

test("encoder dropdown shows the family choices", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  const sel = await screen.findByRole("combobox", { name: /encoder/i });
  expect(sel).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /amd vcn/i })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /cpu \(x265\)/i })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /custom/i })).toBeInTheDocument();
});

test("preset fields are hidden unless Custom is selected", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  const sel = await screen.findByRole("combobox", { name: /encoder/i });
  expect(screen.queryByLabelText(/1080p preset/i)).not.toBeInTheDocument();
  fireEvent.change(sel, { target: { value: "custom" } });
  expect(screen.getByLabelText(/1080p preset/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/4k preset/i)).toBeInTheDocument();
});

test("saving the encoder section sends the family and fallback flag", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  const sel = await screen.findByRole("combobox", { name: /encoder/i });
  fireEvent.change(sel, { target: { value: "vcn" } });
  fireEvent.click(screen.getByRole("button", { name: /save encoder settings/i }));
  await waitFor(() => expect(captured.body).toBeTruthy());
  const body = JSON.parse(captured.body!);
  expect(body.encoder_family).toBe("vcn");
  // Fixture hydrates encoder_fallback_cpu: "false" and the checkbox is left
  // untouched here — proves the untouched hydrated value round-trips as-is.
  expect(body.encoder_fallback_cpu).toBe("false");
});

test("toggling the fallback checkbox flips the saved string", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  await screen.findByRole("combobox", { name: /encoder/i });
  const checkbox = screen.getByRole("checkbox", { name: /fall back to cpu x265/i });
  expect(checkbox).not.toBeChecked();
  fireEvent.click(checkbox);
  expect(checkbox).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: /save encoder settings/i }));
  await waitFor(() => expect(captured.body).toBeTruthy());
  const body = JSON.parse(captured.body!);
  expect(body.encoder_fallback_cpu).toBe("true");
});

test("no availability badges are shown before detection has run", async () => {
  // Unknown is not unavailable: don't label everything "not available" just
  // because nobody has clicked Detect yet.
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  await screen.findByRole("combobox", { name: /encoder/i });
  expect(screen.queryByTestId("enc-avail-vcn")).not.toBeInTheDocument();
});

test("detect shows availability badges", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /detect/i }));
  // Assert on the badges by test id: the family label also appears as an
  // <option> in the dropdown, so a text query would match twice.
  await waitFor(() =>
    expect(screen.getByTestId("enc-avail-vcn")).toHaveTextContent(/AMD VCN: available/i),
  );
  expect(screen.getByTestId("enc-avail-nvenc")).toHaveTextContent(/not available/i);
});

test("warns when the chosen family is known to be unavailable", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /detect/i }));
  const sel = await screen.findByRole("combobox", { name: /encoder/i });
  fireEvent.change(sel, { target: { value: "nvenc" } });
  expect(await screen.findByRole("alert")).toHaveTextContent(/not available/i);
});
