import { flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable, type ColumnDef, type ColumnSizingState, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import * as React from "react";
import { EmptyState } from "@/components/common";
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
/** The narrowest pane in which columns give way to fit; below it the table scrolls. */
const FIT_FROM = 640;

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
    const given = ["label", "status", "tags", "value", "iso"].map((key) => props[key]).find((value) => value !== undefined);
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
  nextStep,
  more,
  highlight,
  find,
}: {
  data: T[];
  columns: Column<T>[];
  label: string;
  initialSort?: SortingState;
  rowId?: (row: T) => string;
  rowLabel?: (row: T) => string;
  selection?: Selection;
  /** Shown instead of the table when there are no rows: a sentence, or an EmptyState with its next step. */
  empty?: React.ReactNode;
  nextStep?: React.ReactNode;
  /** The list continues on the server: the next rows load as the end is scrolled into view. */
  more?: More;
  /** The one row the person came for: marked, and scrolled into view. */
  highlight?: (row: T) => boolean;
  /** A filter box above the rows: keeps the rows with any shown value containing the text. */
  find?: boolean;
}) {
  const [sorting, setSorting] = React.useState<SortingState>(initialSort ?? []);
  // The filter text lives in the address, so a filtered list can be shared or reloaded: one parameter per table.
  const param = `find-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const [query, setQuery] = React.useState(() => (find ? (new URLSearchParams(window.location.search).get(param) ?? "") : ""));
  const change = (text: string) => {
    setQuery(text);
    const next = new URL(window.location.href);
    if (text) next.searchParams.set(param, text);
    else next.searchParams.delete(param);
    window.history.replaceState(window.history.state, "", next);
  };
  const [sizing, setSizing] = React.useState<ColumnSizingState>(() => readWidths(label));
  const prepared = React.useMemo(() => sortable(columns, data), [columns, data]);
  const table = useReactTable({
    data,
    columns: prepared,
    state: { sorting, columnSizing: sizing, globalFilter: find ? query : "" },
    globalFilterFn: "includesString",
    // Every column counts, whatever its first row holds: the default leaves out a column whose first value is empty.
    getColumnCanGlobalFilter: () => true,
    onSortingChange: setSorting,
    onColumnSizingChange: setSizing,
    columnResizeMode: "onChange",
    defaultColumn: { minSize: 64, maxSize: 900, sortDescFirst: false },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });
  React.useEffect(() => saveWidths(label, sizing), [label, sizing]);
  const wrap = React.useMemo(readWrap, []);
  // Columns start at their natural widths; when those add up to more than the pane, the ones nobody resized
  // give way in proportion (down to their minimum), so the table fits instead of scrolling sideways.
  const frame = React.useRef<HTMLDivElement>(null);
  const vacant = empty !== undefined && data.length === 0;
  const [room, setRoom] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = frame.current;
    if (!element) return;
    const measure = () => setRoom(element.clientWidth);
    measure();
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watch?.observe(element);
    return () => watch?.disconnect();
  }, [vacant]);
  const leaves = table.getVisibleLeafColumns();
  const tick = selection && rowId ? 40 : 0;
  const fit = React.useMemo(() => {
    const widths = new Map(leaves.map((c) => [c.id, c.getSize()]));
    const free = leaves.filter((c) => sizing[c.id] === undefined);
    let over = [...widths.values()].reduce((n, w) => n + w, tick) - room;
    // Take the excess from the columns nobody resized, in proportion to their width, never below their minimum.
    // On a phone the columns keep their widths and the table scrolls sideways: squeezed to fit, nothing is readable.
    for (let pass = 0; room >= FIT_FROM && over > 0.5 && pass < 4; pass += 1) {
      const give = free.filter((c) => widths.get(c.id)! > (c.columnDef.minSize ?? 64));
      const pool = give.reduce((n, c) => n + widths.get(c.id)! - (c.columnDef.minSize ?? 64), 0);
      if (pool <= 0) break;
      const share = Math.min(1, over / pool);
      for (const c of give) {
        const floor = c.columnDef.minSize ?? 64;
        const cut = (widths.get(c.id)! - floor) * share;
        widths.set(c.id, Math.floor(widths.get(c.id)! - cut));
        over -= cut;
      }
    }
    return widths;
  }, [leaves, sizing, room, tick]);
  const widthOf = (column: (typeof leaves)[number]): number => fit.get(column.id) ?? column.getSize();
  const fitted = leaves.reduce((n, c) => n + widthOf(c), tick);
  const all = data.length > 0 && !!selection && !!rowId && data.every((row) => selection.ids.has(rowId(row)));
  if (vacant) return typeof empty === "string" ? <EmptyState title={empty} nextStep={nextStep} /> : <>{empty}</>;
  return (
    <div ref={frame} className="w-full min-w-0">
    {find ? (
      <div className="flex items-center gap-3 border-b border-border px-3 py-1.5">
        <input type="search" aria-label={`Filter ${label}`} placeholder="Filter" value={query} onChange={(event) => change(event.target.value)} className="h-7 w-56 rounded-sm border border-border-strong bg-surface px-2 text-xs" />
        {query ? <span className="text-xs text-muted">{table.getRowModel().rows.length} of {data.length}</span> : null}
      </div>
    ) : null}
    <Table aria-label={label} more={more} className="table-fixed" style={{ minWidth: fitted }}>
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
                <Th key={header.id} style={{ width: widthOf(header.column) }} className="truncate" aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}>
                  {header.column.getCanSort() ? (
                    <button type="button" className="inline-flex cursor-pointer items-center gap-1" onClick={header.column.getToggleSortingHandler()}>
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
                        table.setColumnSizing((current) => ({ ...current, [header.column.id]: Math.min(900, Math.max(64, widthOf(header.column) + step)) }));
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
            className={cn("hover:bg-surface-2", wrap ? "h-(--row-wrap)" : "h-(--row)", highlight?.(row.original) && "bg-sidebar-active")}
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
              <Td key={cell.id} style={{ width: widthOf(cell.column) }} title={hover(cell.getValue())}>
                <div className={cn("max-w-full break-words leading-snug", wrap ? "line-clamp-2" : "truncate")}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</div>
              </Td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
    </div>
  );
}
