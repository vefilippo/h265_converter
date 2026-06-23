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
