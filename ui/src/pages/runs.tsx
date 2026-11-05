import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { createColumnHelper, flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import * as React from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { useProjectInfo, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { History, PipelineView, RunView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const PAGE = 50;
const STATUSES = ["FAILED", "IN-PROGRESS", "SUCCESS", "SKIPPED", "LOST"];
const columns = createColumnHelper<RunView>();

export function Runs() {
  const { project: code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const pipeline = params.get("pipeline") ?? "";
  const status = params.get("status") ?? "";
  const tz = useTimezone();
  const info = useProjectInfo(code);
  useDocumentTitle("Runs", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });

  const pipelines = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: PipelineView[] }>(`${project(code)}/pipelines`) });
  const runs = useInfiniteQuery({
    queryKey: ["runs", code, pipeline],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => getJson<History>(`${project(code)}/history`, { all: true, limit: PAGE, pipeline_code: pipeline, before: pageParam }),
    getNextPageParam: (last) => last.before ?? (last.entries.length >= PAGE ? last.entries[last.entries.length - 1]?.pipeline_run_id : undefined),
    refetchInterval: 15_000,
  });

  const all = React.useMemo(() => runs.data?.pages.flatMap((page) => page.entries) ?? [], [runs.data]);
  const rows = React.useMemo(() => (status ? all.filter((run) => run.status === status) : all), [all, status]);
  const [sorting, setSorting] = React.useState<SortingState>([{ id: "id", desc: true }]);

  const table = useReactTable({
    data: rows,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    columns: [
      columns.accessor("pipeline_run_id", {
        id: "id",
        header: "Run",
        cell: (c) => (
          <Link
            className="num font-medium text-accent hover:underline"
            to={runPath(code, c.row.original.pipeline_code, c.getValue())}
          >
            #{c.getValue()}
          </Link>
        ),
      }),
      columns.accessor("pipeline_code", { id: "pipeline", header: "Pipeline", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
      columns.accessor("status", { header: "Status", cell: (c) => <StatusBadge status={c.getValue()} /> }),
      columns.accessor("trigger_kind", { header: "Trigger", cell: (c) => <span className="text-muted">{c.getValue().toLowerCase()}</span> }),
      columns.accessor("run_date", { header: "Logical date", cell: (c) => <span className="num">{c.getValue() ?? "—"}</span> }),
      columns.accessor("start_date", { header: "Started", cell: (c) => <span className="num whitespace-nowrap">{formatTime(c.getValue(), tz)}</span> }),
      columns.display({
        id: "duration",
        header: "Duration",
        cell: (c) => <span className="num">{formatDuration(c.row.original.start_date, c.row.original.end_date)}</span>,
      }),
      columns.accessor("started_by", { header: "Started by", cell: (c) => <span className="text-muted">{c.getValue() ?? "—"}</span> }),
    ],
  });

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader
        title="Pipeline runs"
        subtitle={code}
        actions={
          <div className="flex flex-wrap items-end gap-3">
            <SelectField label="Pipeline" value={pipeline} onChange={(value) => set("pipeline", value)}>
              <option value="">All pipelines</option>
              {(pipelines.data?.pipelines ?? []).map((p) => (
                <option key={p.pipeline_code} value={p.pipeline_code}>
                  {p.pipeline_code}
                </option>
              ))}
            </SelectField>
            <SelectField label="Status" value={status} onChange={(value) => set("status", value)}>
              <option value="">Any status</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s === "IN-PROGRESS" ? "Running" : s.charAt(0) + s.slice(1).toLowerCase()}
                </option>
              ))}
            </SelectField>
            {pipeline || status ? (
              <Button variant="ghost" onClick={() => setParams({}, { replace: true })}>
                Clear filters
              </Button>
            ) : null}
          </div>
        }
      />
      {runs.isError ? <Notice>{(runs.error as Error).message}</Notice> : null}
      <Card>
        <Table aria-label="Pipeline runs">
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
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
                {row.getVisibleCells().map((cell) => (
                  <Td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
        {runs.isPending ? <Loading what="runs" className="p-4" /> : null}
        {runs.isSuccess && rows.length === 0 ? (
          <p className="p-4 text-muted">
            {status ? `None of the ${all.length} loaded runs is ${status.toLowerCase()}. Load more or clear the status filter.` : "No runs yet."}
          </p>
        ) : null}
        <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-xs text-muted">
          <span>
            {rows.length} shown{status ? ` of ${all.length} loaded` : ""}
          </span>
          {runs.hasNextPage ? (
            <Button size="sm" onClick={() => void runs.fetchNextPage()} disabled={runs.isFetchingNextPage}>
              {runs.isFetchingNextPage ? "Loading…" : "Load older runs"}
            </Button>
          ) : (
            <span>All runs loaded</span>
          )}
        </div>
      </Card>
    </div>
  );
}
