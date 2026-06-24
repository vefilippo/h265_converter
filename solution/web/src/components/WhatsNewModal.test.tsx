import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WhatsNewModal } from "./WhatsNewModal";
import { getReleases } from "../changelog";

describe("WhatsNewModal", () => {
  it("renders nothing when closed", () => {
    render(<WhatsNewModal open={false} onClose={() => {}} />);
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
  });

  it("renders resolved release label and entries when open", () => {
    render(<WhatsNewModal open onClose={() => {}} />);
    expect(screen.getByText("What's New")).toBeInTheDocument();
    const first = getReleases("en")[0];
    expect(screen.getByText(first.label)).toBeInTheDocument();
    expect(screen.getByText(`v${first.version}`)).toBeInTheDocument();
    first.entries.forEach((e) => expect(screen.getByText(e)).toBeInTheDocument());
  });
});
