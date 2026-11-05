import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import * as React from "react";
import { Table, Td, Th } from "@/components/ui/table";

// TanStack types a column by its value, so a table's mixed columns share one loose type here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Column<T> = ColumnDef<T, any>;

export interface Selection {
  ids: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onToggleAll: (all: boolean) => void;
}

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
}) {
  const [sorting, setSorting] = React.useState<SortingState>(initialSort ?? []);
  const table = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  const all = data.length > 0 && !!selection && !!rowId && data.every((row) => selection.ids.has(rowId(row)));
  if (empty !== undefined && data.length === 0) return <p className="m-0 p-4 text-muted">{empty}</p>;
  return (
    <Table aria-label={label}>
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
          <tr key={row.id} className="hover:bg-surface-2">
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
              <Td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
