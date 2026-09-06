import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { Button } from "./button";
import { Badge, jobStateLabel } from "./badge";
import { Progress } from "./progress";
import { Select } from "./select";

test("jobStateLabel shows the phase for a running job", () => {
  expect(jobStateLabel({ state: "running", phase: "transcoding" } as any)).toBe("Transcoding");
  expect(jobStateLabel({ state: "running", phase: null } as any)).toBe("running");
  expect(jobStateLabel({ state: "done", phase: null } as any)).toBe("done");
});

test("primitives render", () => {
  render(<><Button>Go</Button><Badge variant="running">running</Badge><Progress value={42} /></>);
  expect(screen.getByText("Go")).toBeInTheDocument();
  expect(screen.getByText("running")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
});

test("Select renders options and reports changes", () => {
  const seen: string[] = [];
  const onChange = vi.fn((e: React.ChangeEvent<HTMLSelectElement>) => {
    seen.push(e.target.value);
  });
  render(
    <Select aria-label="Encoder" value="vcn" onChange={onChange}>
      <option value="vcn">AMD VCN</option>
      <option value="cpu">CPU (x265)</option>
    </Select>,
  );
  const el = screen.getByLabelText("Encoder") as HTMLSelectElement;
  expect(el.value).toBe("vcn");
  fireEvent.change(el, { target: { value: "cpu" } });
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(seen).toEqual(["cpu"]);
});

test("Select forwards its ref to the underlying element", () => {
  const ref = React.createRef<HTMLSelectElement>();
  render(<Select ref={ref} aria-label="Encoder"><option value="cpu">CPU</option></Select>);
  expect(ref.current).toBeInstanceOf(HTMLSelectElement);
});

test("Select merges a caller className with its own", () => {
  render(<Select aria-label="Encoder" className="w-40"><option value="cpu">CPU</option></Select>);
  const el = screen.getByLabelText("Encoder");
  expect(el).toHaveClass("w-40");
  // and it keeps at least one of the primitive's own classes
  expect(el.className.split(" ").length).toBeGreaterThan(1);
});
