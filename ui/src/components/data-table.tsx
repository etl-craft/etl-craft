import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type ColumnSizingState, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import * as React from "react";
import { Table, Td, Th, type More } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const scrollTo = (row: HTMLTableRowElement | null) => row?.scrollIntoView({ block: "nearest" });

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    /** What a column that only draws a cell sorts by, so every column can be sorted. */
    sort?: (row: TData) => string | number | null;
  }
}

// TanStack types a column by its value, so a table's mixed columns share one loose type here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Column<T> = ColumnDef<T, any>;

/** A column for a table of plain records: its value sorts and shows, unless `cell` draws it. */
export interface ColumnSpec<T> {
  id: string;
  header: string;
  value: (row: T) => string | number | null;
  cell?: (row: T) => React.ReactNode;
  size?: number;
}

export function columnsOf<T>(specs: ColumnSpec<T>[]): Column<T>[] {
  return specs.map((spec) => ({
    id: spec.id,
    header: spec.header,
    accessorFn: spec.value,
    size: spec.size,
    cell: (c: { row: { original: T }; getValue: () => unknown }) => (spec.cell ? spec.cell(c.row.original) : (c.getValue() ?? "—")),
  })) as Column<T>[];
}

export interface Selection {
  ids: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onToggleAll: (all: boolean) => void;
}

const WRAP_KEY = "etl-craft-wrap-text";

export function readWrap(): boolean {
  try {
    return window.localStorage.getItem(WRAP_KEY) !== "0";
  } catch {
    return true;
  }
}

const widthKey = (label: string) => `etl-craft-columns:${label}`;

function readWidths(label: string): ColumnSizingState {
  try {
    return JSON.parse(window.localStorage.getItem(widthKey(label)) ?? "{}") as ColumnSizingState;
  } catch {
    return {};
  }
}

function saveWidths(label: string, sizes: ColumnSizingState): void {
  try {
    window.localStorage.setItem(widthKey(label), JSON.stringify(sizes));
  } catch {
    /* the widths last for this page only */
  }
}

/** A column starts as wide as its heading needs, or as its longest value in the first rows, within reason. */
const startWidth = (header: unknown, longest = 0): number => {
  const heading = typeof header === "string" ? Math.max(96, header.length * 9 + 56) : 120;
  return Math.round(Math.min(360, Math.max(heading, longest * 7.2 + 32)));
};

/** How many characters the longest plain value of a column has in the first rows. */
function widest<T>(column: Column<T>, data: T[]): number {
  const value = "accessorFn" in column ? (column.accessorFn as (row: T, index: number) => unknown) : "accessorKey" in column ? (row: T) => (row as Record<string, unknown>)[String(column.accessorKey)] : null;
  if (!value) return 0;
  return Math.min(60, Math.max(0, ...data.slice(0, 100).map((row, index) => { const v = value(row, index); return typeof v === "string" || typeof v === "number" ? String(v).length : 0; })));
}

export function saveWrap(on: boolean): void {
  try {
    window.localStorage.setItem(WRAP_KEY, on ? "1" : "0");
  } catch {
    /* the choice lasts for this page only */
  }
}

/** The full value shows on hover; only plain values have one. */
const hover = (value: unknown): string | undefined => (typeof value === "string" || typeof value === "number" ? String(value) : undefined);

/** The words a drawn cell shows, for sorting: text as is, and for a badge, a link or a tag list what it was given. */
function textOf(node: unknown): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(" ");
  if (React.isValidElement(node)) {
    const props = node.props as Record<string, unknown>;
    if (props.children !== undefined) return textOf(props.children);
    const given = ["label", "status", "tags", "value"].map((key) => props[key]).find((value) => value !== undefined);
    return Array.isArray(given) ? given.join(" ") : textOf(given);
  }
  return "";
}

const ACTIONS = /^(act|actions?|controls?)$/i;

/** Every column can be sorted: one that only draws a cell sorts by what it names in `meta.sort`, or else by what it shows. */
function sortable<T>(columns: Column<T>[], data: T[]): Column<T>[] {
  return columns.map((column) => {
    const own = "accessorKey" in column || "accessorFn" in column;
    const base = column.size === undefined ? { ...column, size: startWidth(column.header, widest(column, data)) } : column;
    if (own) return base;
    const header = typeof column.header === "string" ? column.header : "";
    if (!column.meta?.sort && (ACTIONS.test(column.id ?? "") || ACTIONS.test(header))) return { ...base, enableSorting: false } as Column<T>;
    const draw = column.cell;
    const shown = (row: T): string => {
      const context = { row: { original: row }, getValue: () => undefined, renderValue: () => undefined, column: { id: column.id } };
      return typeof draw === "function" ? textOf((draw as (c: unknown) => unknown)(context)) : "";
    };
    const accessor = column.meta?.sort ?? shown;
    const grown = column.size === undefined ? { ...base, size: startWidth(column.header, widest({ id: column.id ?? "column", accessorFn: accessor } as Column<T>, data)) } : base;
    return { ...grown, accessorFn: accessor, enableSorting: true } as Column<T>;
  });
}

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
  const [sizing, setSizing] = React.useState<ColumnSizingState>(() => readWidths(label));
  const prepared = React.useMemo(() => sortable(columns, data), [columns, data]);
  const table = useReactTable({
    data,
    columns: prepared,
    state: { sorting, columnSizing: sizing },
    onSortingChange: setSorting,
    onColumnSizingChange: setSizing,
    columnResizeMode: "onChange",
    defaultColumn: { minSize: 64, maxSize: 900, sortDescFirst: false },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  React.useEffect(() => saveWidths(label, sizing), [label, sizing]);
  const wrap = React.useMemo(readWrap, []);
  const all = data.length > 0 && !!selection && !!rowId && data.every((row) => selection.ids.has(rowId(row)));
  if (empty !== undefined && data.length === 0) return <p className="m-0 p-4 text-muted">{empty}</p>;
  return (
    <>

    <Table aria-label={label} more={more} className="table-fixed" style={{ minWidth: table.getTotalSize() }}>
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
                <Th key={header.id} style={{ width: header.getSize() }} className="truncate" aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                  {header.column.getCanSort() ? (
                    <button type="button" className="inline-flex cursor-pointer items-center gap-1 uppercase" onClick={header.column.getToggleSortingHandler()}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sorted === "asc" ? <ArrowUp className="size-3" aria-hidden /> : sorted === "desc" ? <ArrowDown className="size-3" aria-hidden /> : null}
                    </button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                  {header.column.getCanResize() ? (
                    <div
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={`Resize the ${typeof header.column.columnDef.header === "string" ? header.column.columnDef.header : header.column.id} column`}
                      tabIndex={0}
                      title="Drag to resize; double-click to reset"
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                      onDoubleClick={() => header.column.resetSize()}
                      onKeyDown={(event) => {
                        const step = event.key === "ArrowLeft" ? -16 : event.key === "ArrowRight" ? 16 : 0;
                        if (!step) return;
                        event.preventDefault();
                        table.setColumnSizing((current) => ({ ...current, [header.column.id]: Math.min(900, Math.max(64, header.column.getSize() + step)) }));
                      }}
                      className={cn("group absolute right-0 top-0 flex h-full w-3 cursor-col-resize touch-none select-none items-center justify-center outline-none", header.column.getIsResizing() ? "bg-accent/20" : "hover:bg-accent/15 focus-visible:bg-accent/20")}
                    >
                      <span aria-hidden className={cn("h-4 w-px rounded-full bg-border-strong transition-all group-hover:h-5 group-hover:w-0.5 group-hover:bg-accent group-focus-visible:h-5 group-focus-visible:w-0.5 group-focus-visible:bg-accent", header.column.getIsResizing() && "h-5 w-0.5 bg-accent")} />
                    </div>
                  ) : null}
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
            className={cn("hover:bg-surface-2", wrap ? "h-11" : "h-8", highlight?.(row.original) && "bg-sidebar-active")}
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
              <Td key={cell.id} style={{ width: cell.column.getSize() }} title={hover(cell.getValue())}>
                <div className={cn("max-w-full break-words leading-snug", wrap ? "line-clamp-2" : "truncate")}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</div>
              </Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
    </>
  );
}
