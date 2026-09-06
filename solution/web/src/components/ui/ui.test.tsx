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
  const onChange = vi.fn();
  render(
    <Select aria-label="Encoder" value="vcn" onChange={onChange}>
      <option value="vcn">AMD VCN</option>
      <option value="cpu">CPU (x265)</option>
    </Select>,
  );
  const el = screen.getByLabelText("Encoder") as HTMLSelectElement;
  expect(el.value).toBe("vcn");
  fireEvent.change(el, { target: { value: "cpu" } });
  expect(onChange).toHaveBeenCalled();
});
