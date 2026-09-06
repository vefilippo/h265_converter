import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import Setup from "./Setup";

afterEach(() => vi.restoreAllMocks());

test("password step posts and advances to connections", async () => {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  render(<Setup onDone={() => {}} />);
  await userEvent.type(screen.getByLabelText(/password/i), "hunter2");
  await userEvent.click(screen.getByRole("button", { name: /create password/i }));

  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith("/api/setup/password", expect.objectContaining({ method: "POST" })));
  // Advanced to the connections step.
  expect(await screen.findByText(/sonarr/i)).toBeInTheDocument();
});

test("can skip optional steps to finish", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ ok: true }), { status: 200 })));
  const onDone = vi.fn();

  render(<Setup onDone={onDone} />);
  await userEvent.type(screen.getByLabelText(/password/i), "hunter2");
  await userEvent.click(screen.getByRole("button", { name: /create password/i }));

  // Skip connections, then skip HandBrake, then finish.
  await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
  await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
  await userEvent.click(await screen.findByRole("button", { name: /finish|go to dashboard/i }));

  await waitFor(() => expect(onDone).toHaveBeenCalled());
});

const DETECT_OK = {
  ok: true,
  available: ["cpu", "vcn"],
  detected_at: "2026-09-05T17:00:00Z",
  families: [
    { id: "vcn", label: "AMD VCN", preset_1080: "H.265 VCN 1080p", preset_4k: "H.265 VCN 2160p 4K", hardware: true, available: true },
    { id: "cpu", label: "CPU (x265)", preset_1080: "H.265 MKV 1080p30", preset_4k: "H.265 MKV 2160p60 4K", hardware: false, available: true },
  ],
};

const DETECT_FAIL = {
  ok: false,
  error: "Could not run hb.exe. Check the HandBrake CLI path.",
  available: [],
  detected_at: null,
  families: [],
};

function stubFetch(detectBody: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = url.includes("/api/encoders/detect") ? detectBody : { ok: true };
    return new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }));
}

/** Render the wizard and advance password -> connections -> handbrake step. */
async function gotoHandbrakeStep() {
  render(<Setup onDone={() => {}} />);
  await userEvent.type(screen.getByLabelText(/password/i), "hunter2");
  await userEvent.click(screen.getByRole("button", { name: /create password/i }));
  // Skip connections; the next screen is the HandBrake step.
  await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
}

test("wizard detects encoders and reports the hardware found", async () => {
  stubFetch(DETECT_OK);
  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  expect(await screen.findByText(/Found AMD VCN/i)).toBeInTheDocument();
});

test("wizard reports when detection fails", async () => {
  stubFetch(DETECT_FAIL);
  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  expect(await screen.findByText(/could not run/i)).toBeInTheDocument();
});

test("wizard saves the detected family with the CLI path", async () => {
  stubFetch(DETECT_OK);
  await gotoHandbrakeStep();
  await userEvent.type(screen.getByPlaceholderText(/HandBrakeCLI/i), "C:/hb/HandBrakeCLI.exe");
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  await screen.findByText(/Found AMD VCN/i);
  await userEvent.click(screen.getByRole("button", { name: /save & continue/i }));

  await waitFor(() => {
    const put = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (c) => String(c[0]).includes("/api/settings"),
    );
    expect(put).toBeTruthy();
    expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({
      handbrake_cli: "C:/hb/HandBrakeCLI.exe",
      encoder_family: "vcn",
    });
  });
});

const DETECT_NO_HARDWARE = {
  ok: true,
  available: ["cpu"],
  detected_at: "2026-09-05T17:00:00Z",
  families: [
    { id: "vcn", label: "AMD VCN", preset_1080: "H.265 VCN 1080p", preset_4k: "H.265 VCN 2160p 4K", hardware: true, available: false },
    { id: "cpu", label: "CPU (x265)", preset_1080: "H.265 MKV 1080p30", preset_4k: "H.265 MKV 2160p60 4K", hardware: false, available: true },
  ],
};

test("detection finding no hardware falls back to cpu", async () => {
  stubFetch(DETECT_NO_HARDWARE);
  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  expect(await screen.findByText(/no hardware encoder found/i)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /save & continue/i }));
  await waitFor(() => {
    const put = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (c) => String(c[0]).includes("/api/settings"),
    );
    expect(put).toBeTruthy();
    expect(JSON.parse((put![1] as RequestInit).body as string).encoder_family).toBe("cpu");
  });
});

test("a failed detection request surfaces an error and does not crash", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/encoders/detect")) {
      return Promise.reject(new Error("network down"));
    }
    return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  }));

  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));

  expect(await screen.findByText(/detection failed/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /detect/i })).toBeEnabled();
});

test("Save & continue is disabled while detection is in flight", async () => {
  let resolveDetect: (value: Response) => void = () => {};
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/encoders/detect")) {
      return new Promise<Response>((resolve) => { resolveDetect = resolve; });
    }
    return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  }));

  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));

  expect(screen.getByRole("button", { name: /save & continue/i })).toBeDisabled();

  resolveDetect(new Response(JSON.stringify(DETECT_OK), {
    status: 200, headers: { "Content-Type": "application/json" },
  }));
  await screen.findByText(/Found AMD VCN/i);
});

test("skipping detection does not write an encoder family", async () => {
  let putBody: string | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/settings") && init?.method === "PUT") {
      putBody = init.body as string;
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  }));

  await gotoHandbrakeStep();
  await userEvent.type(screen.getByPlaceholderText(/HandBrakeCLI/i), "C:/hb.exe");
  await userEvent.click(screen.getByRole("button", { name: /save & continue/i }));

  await waitFor(() => expect(putBody).toBeTruthy());
  expect(JSON.parse(putBody!)).toEqual({ handbrake_cli: "C:/hb.exe" });
});
