import { render, screen } from "@testing-library/react";
import { Button } from "./button";
import { Badge } from "./badge";
import { Progress } from "./progress";

test("primitives render", () => {
  render(<><Button>Go</Button><Badge variant="running">running</Badge><Progress value={42} /></>);
  expect(screen.getByText("Go")).toBeInTheDocument();
  expect(screen.getByText("running")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
});
