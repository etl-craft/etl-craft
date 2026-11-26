import { RunLabel } from "@/components/run-label";
import { useInfiniteQuery } from "@tanstack/react-query";
import { words } from "@/lib/labels";
import { When } from "@/components/when";
import * as React from "react";
import { Loading, Notice } from "@/components/common";
import { createColumnHelper } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { Card } from "@/components/ui/card";
import { getJson, project } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { History, RunView } from "@/lib/types";

const PAGE = 50;
const columns = createColumnHelper<RunView>();

/** A project's runs, or one pipeline's, newest first, loaded a page at a time. */
export interface RunFilters {
  pool?: string;
  agent?: string;
  failure_class?: string;
  /** Only runs in these states, chosen in the database so paging keeps finding them. */
  run_status?: string[];
}

/** A project's runs, or one pipeline's, newest first, a page at a time; every view of the runs shares it. */
export function useRuns(code: string, pipeline?: string, filters: RunFilters = {}, grid?: { limit: number; selected?: number }) {
  const runs = useInfiniteQuery({
    queryKey: ["runs", code, pipeline ?? "", filters.pool ?? "", filters.agent ?? "", filters.failure_class ?? "", (filters.run_status ?? []).join(","), ...(grid ? [grid] : [])],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => getJson<History>(`${project(code)}/history`, { all: true, limit: grid?.limit ?? PAGE, cells: grid ? true : undefined, extra_run_id: pageParam === undefined ? grid?.selected : undefined, pipeline_code: pipeline, before: pageParam, pool: filters.pool, agent: filters.agent, failure_class: filters.failure_class, run_status: filters.run_status }),
    getNextPageParam: (last) => last.before ?? (!grid && last.entries.length >= PAGE ? last.entries[last.entries.length - 1]?.pipeline_run_id : undefined),
    refetchInterval: 15_000,
  });
  const all = React.useMemo(() => runs.data?.pages.flatMap((page) => page.entries) ?? [], [runs.data]);
  return { runs, all };
}

/** The runs of the project, or of one pipeline, as a table. A run opens its own page from a pipeline's list, and
 * its pipeline's list with the run highlighted from the project's. */
export function RunsTable({ code, pipeline, status, codes, filters = {}, highlight }: { code: string; pipeline?: string; status?: string; codes?: ReadonlySet<string>; filters?: RunFilters; highlight?: number }) {
  const { runs, all } = useRuns(code, pipeline, filters);
  const rows = React.useMemo(() => all.filter((run) => (!status || run.status === status) && (!codes || codes.has(run.pipeline_code))), [all, status, codes]);
  return (
    <>
      {runs.isError ? <Notice>{(runs.error as Error).message}</Notice> : null}
      <Card>
        <DataTable
          label="Pipeline runs"
          stacked
          data={rows}
          highlight={highlight === undefined ? undefined : (run) => run.pipeline_run_id === highlight}
          initialSort={[{ id: "id", desc: true }]}
          nextStep="Run a pipeline from Pipelines, or clear the filters to see recorded runs."
          empty={runs.isSuccess && !runs.hasNextPage ? (status || codes ? `None of the ${all.length} runs matches the filters. Clear a filter.` : "No runs yet.") : undefined}
          more={{ hasMore: Boolean(runs.hasNextPage), loading: runs.isFetchingNextPage, load: () => void runs.fetchNextPage() }}
          columns={[
            columns.accessor("pipeline_run_id", {
              id: "id",
              header: "Run",
              cell: (c) => (
                <RunLabel truncate id={c.getValue()} label={c.row.original.run_label} to={runPath(code, c.row.original.pipeline_code, c.getValue())} />
              ),
            }),
            // Status precedes the remaining fields in both the table and phone cards.
            columns.accessor("status", { header: "Status", cell: (c) => <StatusBadge quiet status={c.getValue()} /> }),
            ...(pipeline ? [] : [columns.accessor("pipeline_code", { id: "pipeline", header: "Pipeline", cell: (c) => <span className="font-medium">{c.getValue()}</span> })]),
            columns.accessor("trigger_kind", { header: "Trigger", cell: (c) => <span className="text-muted">{words(c.getValue()).toLowerCase()}{c.row.original.backfill ? " · backfill" : ""}{c.row.original.full_refresh ? " · full refresh" : ""}</span> }),
            columns.accessor("run_date", { header: "Logical date", cell: (c) => <span className="num">{c.getValue() ?? "—"}</span> }),
            columns.accessor("start_date", { header: "Started", cell: (c) => <When iso={c.getValue()} /> }),
            columns.display({ id: "duration", header: "Duration", cell: (c) => <span className="num">{formatDuration(c.row.original.start_date, c.row.original.end_date)}</span> }),
            columns.accessor("started_by", { header: "Started by", cell: (c) => <span className="text-muted">{c.getValue() ?? "—"}</span> }),
          ]}
        />
        {runs.isPending ? <Loading what="runs" className="p-4" /> : null}
      </Card>
    </>
  );
}
