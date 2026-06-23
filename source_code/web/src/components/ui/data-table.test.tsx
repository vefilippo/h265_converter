import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "./data-table";

type Row = { id: number; name: string; locked: boolean };

const COLS: ColumnDef<Row, unknown>[] = [
  { id: "name", header: "Name", accessorKey: "name" },
];

const DATA: Row[] = [
  { id: 1, name: "alpha", locked: false },
  { id: 2, name: "beta", locked: true },
  { id: 3, name: "gamma", locked: false },
];

test("select-all selects only selectable rows", () => {
  const onSelectionChange = vi.fn();
  render(
    <DataTable
      columns={COLS}
      data={DATA}
      getRowId={(r) => String(r.id)}
      enableSelection
      isRowSelectable={(r) => !r.locked}
      onSelectionChange={onSelectionChange}
    />,
  );

  // the locked row's checkbox is disabled
  const boxes = screen.getAllByRole("checkbox");
  // boxes[0] is the header select-all
  const header = boxes[0];
  fireEvent.click(header);

  const calls = onSelectionChange.mock.calls;
  const last = calls[calls.length - 1]?.[0] as Row[];
  expect(last.map((r) => r.id).sort()).toEqual([1, 3]);
});

const DATA5: Row[] = [
  { id: 1, name: "a", locked: false },
  { id: 2, name: "b", locked: false },
  { id: 3, name: "c", locked: true },
  { id: 4, name: "d", locked: false },
  { id: 5, name: "e", locked: false },
];

test("shift-click selects the range between anchor and target, skipping non-selectable rows", () => {
  const onSelectionChange = vi.fn();
  render(
    <DataTable
      columns={COLS}
      data={DATA5}
      getRowId={(r) => String(r.id)}
      enableSelection
      isRowSelectable={(r) => !r.locked}
      onSelectionChange={onSelectionChange}
    />,
  );

  // Row checkboxes render in data order (no sorting): indices 0..4 -> ids 1..5.
  const rowBoxes = screen.getAllByLabelText("Select row");
  fireEvent.click(rowBoxes[0]); // anchor = id 1
  fireEvent.click(rowBoxes[3], { shiftKey: true }); // shift-click id 4

  const calls = onSelectionChange.mock.calls;
  const last = calls[calls.length - 1]?.[0] as Row[];
  // Range 1..4 inclusive, with id 3 locked (skipped) => 1, 2, 4.
  expect(last.map((r) => r.id).sort()).toEqual([1, 2, 4]);
});

test("locked row checkbox is disabled", () => {
  render(
    <DataTable
      columns={COLS}
      data={DATA}
      getRowId={(r) => String(r.id)}
      enableSelection
      isRowSelectable={(r) => !r.locked}
    />,
  );
  // 1 header + 3 rows = 4 checkboxes; the beta (locked) one is disabled
  const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
  const disabled = boxes.filter((b) => b.disabled);
  expect(disabled.length).toBe(1);
});
