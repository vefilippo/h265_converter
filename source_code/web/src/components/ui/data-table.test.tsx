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
