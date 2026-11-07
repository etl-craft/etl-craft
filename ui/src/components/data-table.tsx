import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import * as React from "react";
import { Table, Td, Th, type More } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const scrollTo = (row: HTMLTableRowElement | null) => row?.scrollIntoView({ block: "nearest" });

// TanStack types a column by its value, so a table's mixed columns share one loose type here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Column<T> = ColumnDef<T, any>;

export interface Selection {
  ids: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onToggleAll: (all: boolean) => void;
}

const WRAP_KEY = "etl-craft-wrap-text";

function readWrap(): boolean {
  try {
    return window.localStorage.getItem(WRAP_KEY) === "1";
  } catch {
    return false;
  }
}

function saveWrap(on: boolean): void {
  try {
    window.localStorage.setItem(WRAP_KEY, on ? "1" : "0");
  } catch {
    /* the choice lasts for this page only */
  }
}

/** The full value shows on hover while cells do not wrap; only plain values have one. */
const hover = (value: unknown): string | undefined => (typeof value === "string" || typeof value === "number" ? String(value) : undefined);

/** The one table every list uses: sortable headers, a label for assistive technology, optional row selection. */
export function DataTable<T>({
  data,
  columns,
  label,
  initialSort,
  rowId,
  rowLabel,
  selection,
  empty,
  more,
  highlight,
}: {
  data: T[];
  columns: Column<T>[];
  label: string;
  initialSort?: SortingState;
  rowId?: (row: T) => string;
  rowLabel?: (row: T) => string;
  selection?: Selection;
  /** Shown instead of the table when there are no rows. */
  empty?: string;
  /** The list continues on the server: the next rows load as the end is scrolled into view. */
  more?: More;
  /** The one row the person came for: marked, and scrolled into view. */
  highlight?: (row: T) => boolean;
}) {
  const [sorting, setSorting] = React.useState<SortingState>(initialSort ?? []);
  const table = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  const [wrap, setWrap] = React.useState(readWrap);
  const all = data.length > 0 && !!selection && !!rowId && data.every((row) => selection.ids.has(rowId(row)));
  if (empty !== undefined && data.length === 0) return <p className="m-0 p-4 text-muted">{empty}</p>;
  return (
    <>
      <label className="flex cursor-pointer items-center justify-end gap-2 px-3 py-1.5 text-xs text-muted">
        <input
          type="checkbox"
          checked={wrap}
          onChange={(event) => {
            setWrap(event.target.checked);
            saveWrap(event.target.checked);
          }}
        />
        Wrap text
      </label>
    <Table aria-label={label} more={more}>
      <thead>
        {table.getHeaderGroups().map((group) => (
          <tr key={group.id}>
            {selection && rowId ? (
              <Th className="w-10">
                <input type="checkbox" aria-label={`Select every row of ${label}`} checked={all} onChange={(event) => selection.onToggleAll(event.target.checked)} />
              </Th>
            ) : null}
            {group.headers.map((header) => {
              const sorted = header.column.getIsSorted();
              return (
                <Th key={header.id} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                  {header.column.getCanSort() ? (
                    <button type="button" className="inline-flex cursor-pointer items-center gap-1 uppercase" onClick={header.column.getToggleSortingHandler()}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sorted === "asc" ? <ArrowUp className="size-3" aria-hidden /> : sorted === "desc" ? <ArrowDown className="size-3" aria-hidden /> : null}
                    </button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                </Th>
              );
            })}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr
            key={row.id}
            ref={highlight?.(row.original) ? scrollTo : undefined}
            aria-current={highlight?.(row.original) ? "true" : undefined}
            className={cn("hover:bg-surface-2", highlight?.(row.original) && "bg-sidebar-active")}
          >
            {selection && rowId ? (
              <Td>
                <input
                  type="checkbox"
                  aria-label={`Select ${rowLabel ? rowLabel(row.original) : rowId(row.original)}`}
                  checked={selection.ids.has(rowId(row.original))}
                  onChange={() => selection.onToggle(rowId(row.original))}
                />
              </Td>
            ) : null}
            {row.getVisibleCells().map((cell) => (
              <Td key={cell.id} className={wrap ? "break-words" : "whitespace-nowrap"} title={hover(cell.getValue())}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
    </>
  );
}
