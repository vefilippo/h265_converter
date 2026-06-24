import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VersionBadge } from "./VersionBadge";

vi.mock("../hooks/queries", () => ({
  useVersion: () => ({ data: { version: "1.0.0" } }),
}));

beforeEach(() => {
  localStorage.clear();
});

describe("VersionBadge", () => {
  it("renders the fetched version", () => {
    localStorage.setItem("h265:lastSeenVersion", "1.0.0"); // suppress auto-open
    render(<VersionBadge />);
    expect(screen.getByText("v1.0.0")).toBeInTheDocument();
  });

  it("opens the What's New modal on click", async () => {
    localStorage.setItem("h265:lastSeenVersion", "1.0.0"); // suppress auto-open
    render(<VersionBadge />);
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("v1.0.0"));
    expect(screen.getByText("What's New")).toBeInTheDocument();
  });
});
