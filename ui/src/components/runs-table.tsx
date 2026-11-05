import { useInfiniteQuery } from "@tanstack/react-query";
import * as React from "react";
import { Link } from "react-router-dom";
import { Loading, Notice } from "@/components/common";
import { createColumnHelper } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { History, RunView } from "@/lib/types";

const PAGE = 50;
const columns = createColumnHelper<RunView>();

/** A project's runs, or one pipeline's, newest first, loaded a page at a time. */
export function RunsTable({ code, pipeline, status, onRuns }: { code: string; pipeline?: string; status?: string; onRuns?: (runs: RunView[]) => void }) {
  const tz = useTimezone();
  const runs = useInfiniteQuery({
    queryKey: ["runs", code, pipeline ?? ""],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => getJson<History>(`${project(code)}/history`, { all: true, limit: PAGE, pipeline_code: pipeline, before: pageParam }),
    getNextPageParam: (last) => last.before ?? (last.entries.length >= PAGE ? last.entries[last.entries.length - 1]?.pipeline_run_id : undefined),
    refetchInterval: 15_000,
  });
  const all = React.useMemo(() => runs.data?.pages.flatMap((page) => page.entries) ?? [], [runs.data]);
  React.useEffect(() => onRuns?.(all), [all, onRuns]);
  const rows = React.useMemo(() => (status ? all.filter((run) => run.status === status) : all), [all, status]);
  return (
    <>
      {runs.isError ? <Notice>{(runs.error as Error).message}</Notice> : null}
      <Card>
        <DataTable
          label="Pipeline runs"
          data={rows}
          initialSort={[{ id: "id", desc: true }]}
          empty={runs.isSuccess ? (status ? `None of the ${all.length} loaded runs is ${status.toLowerCase()}. Load more or clear the status filter.` : "No runs yet.") : undefined}
          columns={[
            columns.accessor("pipeline_run_id", {
              id: "id",
              header: "Run",
              cell: (c) => (
                <Link className="num font-medium text-accent hover:underline" to={runPath(code, c.row.original.pipeline_code, c.getValue())}>
                  #{c.getValue()}
                </Link>
              ),
            }),
            ...(pipeline ? [] : [columns.accessor("pipeline_code", { id: "pipeline", header: "Pipeline", cell: (c) => <span className="font-medium">{c.getValue()}</span> })]),
            columns.accessor("status", { header: "Status", cell: (c) => <StatusBadge status={c.getValue()} /> }),
            columns.accessor("trigger_kind", { header: "Trigger", cell: (c) => <span className="text-muted">{c.getValue().toLowerCase()}{c.row.original.backfill ? " · backfill" : ""}</span> }),
            columns.accessor("run_date", { header: "Logical date", cell: (c) => <span className="num">{c.getValue() ?? "—"}</span> }),
            columns.accessor("start_date", { header: "Started", cell: (c) => <span className="num whitespace-nowrap">{formatTime(c.getValue(), tz)}</span> }),
            columns.display({ id: "duration", header: "Duration", cell: (c) => <span className="num">{formatDuration(c.row.original.start_date, c.row.original.end_date)}</span> }),
            columns.accessor("started_by", { header: "Started by", cell: (c) => <span className="text-muted">{c.getValue() ?? "—"}</span> }),
          ]}
        />
        {runs.isPending ? <Loading what="runs" className="p-4" /> : null}
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
    </>
  );
}
