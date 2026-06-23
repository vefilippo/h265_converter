import { render, screen } from "@testing-library/react";
import { Button } from "./button";
import { Badge, jobStateLabel } from "./badge";
import { Progress } from "./progress";

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
