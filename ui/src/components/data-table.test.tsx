import { createColumnHelper } from "@tanstack/react-table";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { columnsOf, DataTable, saveWrap } from "@/components/data-table";

interface Row {
  name: string;
  size: number;
}
const rows: Row[] = [
  { name: "beta", size: 3 },
  { name: "alpha", size: 20 },
  { name: "gamma", size: 1 },
];
const helper = createColumnHelper<Row>();
const names = () => within(screen.getByRole("table", { name: "Things" })).getAllByRole("row").slice(1).map((r) => r.textContent);

describe("the shared table", () => {
  beforeEach(() => window.localStorage.clear());

  it("sorts a column that only draws a cell by what it shows", () => {
    const columns = [helper.display({ id: "label", header: "Label", cell: (c) => <b>{c.row.original.name}</b> })];
    render(<DataTable label="Things" data={rows} columns={columns} />);
    fireEvent.click(screen.getByRole("button", { name: /Label/ }));
    expect(names()).toEqual(["alpha", "beta", "gamma"]);
    fireEvent.click(screen.getByRole("button", { name: /Label/ }));
    expect(names()).toEqual(["gamma", "beta", "alpha"]);
  });

  it("sorts numbers as numbers", () => {
    render(<DataTable label="Things" data={rows} columns={columnsOf<Row>([{ id: "size", header: "Size", value: (r) => r.size }])} />);
    fireEvent.click(screen.getByRole("button", { name: /Size/ }));
    expect(names()).toEqual(["1", "3", "20"]);
  });

  it("leaves an actions column unsortable", () => {
    const columns = [helper.display({ id: "act", header: "Actions", cell: () => <button type="button">Do</button> })];
    render(<DataTable label="Things" data={rows} columns={columns} />);
    expect(screen.queryByRole("button", { name: /Actions/ })).toBeNull();
  });

  it("resizes a column from the keyboard and remembers the width", () => {
    const columns = columnsOf<Row>([{ id: "name", header: "Name", value: (r) => r.name, size: 200 }]);
    const { unmount } = render(<DataTable label="Things" data={rows} columns={columns} />);
    const handle = screen.getByRole("separator", { name: "Resize the Name column" });
    const width = () => (screen.getByRole("columnheader", { name: /Name/ }) as HTMLElement).style.width;
    expect(width()).toBe("200px");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(width()).toBe("216px");
    unmount();
    render(<DataTable label="Things" data={rows} columns={columns} />);
    expect(width()).toBe("216px");
  });

  it("wraps long text by default with every row the same height, and one line when the preference is off", () => {
    const { unmount } = render(<DataTable label="Things" data={rows} columns={columnsOf<Row>([{ id: "name", header: "Name", value: (r) => r.name }])} />);
    const body = within(screen.getByRole("table", { name: "Things" })).getAllByRole("row").slice(1);
    expect(new Set(body.map((r) => r.className.match(/h-\d+/)?.[0])).size).toBe(1);
    expect(body[0]!.className).toContain("h-11");
    expect(body[0]!.querySelector(".line-clamp-2")).toBeTruthy();
    unmount();
    saveWrap(false);
    render(<DataTable label="Things" data={rows} columns={columnsOf<Row>([{ id: "name", header: "Name", value: (r) => r.name }])} />);
    expect(within(screen.getByRole("table", { name: "Things" })).getAllByRole("row")[1]!.className).toContain("h-8");
  });

  it("shows a divider between columns without having to find it with the pointer", () => {
    render(<DataTable label="Things" data={rows} columns={columnsOf<Row>([{ id: "name", header: "Name", value: (r) => r.name }])} />);
    const handle = screen.getByRole("separator", { name: "Resize the Name column" });
    expect(handle.querySelector("span")).toBeTruthy(); // the line is always drawn
  });
});
