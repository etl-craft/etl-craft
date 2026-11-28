import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { compactCount, cores, executionSeconds, interval, MedianMark, memory, perSecond } from "@/components/attempt-triage";
import { Loading, Notice, SelectField } from "@/components/common";
import { DataTable, columnsOf } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useNow } from "@/components/when";
import { getJson, project } from "@/lib/api";
import { formatSeconds, formatTime } from "@/lib/format";
import { useTimezone } from "@/hooks";
import type { AttemptView, MetricMedian, RunView } from "@/lib/types";

type Attempt = { exit_name?: string | null } & Pick<AttemptView, "attempt_id" | "attempt_number" | "status" | "started_at" | "ended_at" | "source_count" | "rows_written" | "reject_count" | "peak_rss_bytes" | "cpu_seconds" | "error_message" | "failure_code">;
type Task = { task_code: string; status: string | null; handler: string; error_message: string | null; attempts: Attempt[]; duration: MetricMedian };
type Row = { task: Task; attempt?: Attempt; earlier?: boolean };
type Breakdown = { rows: { reason: string; count: number }[]; reject_table: string | null; recorded_count: number; retention_removed_at: string | null };

const pageSize = 100;
const formats = {
  read: compactCount, written: compactCount, rejected: compactCount,
  rate: compactCount, memory, cpu: cores, duration: formatSeconds,
};
const labels = {
  task: "Task", status: "Status", try: "Try", duration: "Duration", read: "Read",
  written: "Written", rejected: "Rejected", rate: "Rows a second", memory: "Peak memory", cpu: "CPU",
};
type Column = keyof typeof labels;
function values(row: Row, now: string) {
  const a = row.attempt;
  const duration = a ? executionSeconds(a, now) : null;
  return {
    task: row.task.task_code, status: a?.status ?? row.task.status ?? "NOT_STARTED",
    try: a?.attempt_number, duration, read: a?.source_count, written: a?.rows_written,
    rejected: a?.reject_count, rate: perSecond(a?.source_count, duration), memory: a?.peak_rss_bytes,
    cpu: perSecond(a?.cpu_seconds, interval(a?.started_at, a?.ended_at)),
  };
}

export function useRunStatistics(code: string, run?: RunView) {
  return useQuery({
    queryKey: ["run-statistics", code, run?.pipeline_run_id, run?.end_date],
    queryFn: () => getJson<{tasks: Task[]}>(`${project(code)}/runs/${run?.pipeline_run_id}/statistics`),
    enabled: run !== undefined,
    refetchInterval: run && !run.end_date ? 5_000 : false,
  });
}

export function RunStatistics({ code, run, stats, onTask }: {
  code: string; run: RunView; stats: UseQueryResult<{tasks: Task[]}>; onTask: (task: string, firstError?: boolean, attemptNumber?: number) => void;
}) {
  const [params, setParams] = useSearchParams();
  const [rejectTask, setRejectTask] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const now = new Date(useNow()).toISOString();
  const [rawBy, direction] = (params.get("statisticsSort") ?? "task:asc").split(":");
  const by = Object.hasOwn(labels, rawBy ?? "") ? rawBy as Column : "task";
  const desc = direction === "desc";
  function change(sort: Column, descending: boolean, page: number) {
    const next = new URLSearchParams(params);
    next.set("statisticsSort", `${sort}:${descending ? "desc" : "asc"}`);
    if (page > 1) next.set("statisticsPage", String(page));
    else next.delete("statisticsPage");
    setParams(next, { replace: true });
  }
  const rows = (stats.data?.tasks ?? []).map(task => ({ task, attempt: task.attempts.at(-1) })).sort((left, right) => {
    const a = values(left, now)[by], b = values(right, now)[by];
    if (a == null || b == null) return Number(a == null) - Number(b == null);
    const order = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
    return order * (desc ? -1 : 1) || left.task.task_code.localeCompare(right.task.task_code);
  });
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const page = Math.max(1, Math.min(pages, Number.parseInt(params.get("statisticsPage") ?? "", 10) || 1));
  const pageRows: Row[] = rows.slice((page - 1) * pageSize, page * pageSize).flatMap(row => [
    row,
    ...(expanded.has(row.task.task_code) ? row.task.attempts.slice(0, -1).map(attempt => ({
      task: row.task, attempt, earlier: true,
    })) : []),
  ]);
  function toggle(task: string) {
    setExpanded(previous => {
      const next = new Set(previous);
      if (next.has(task)) next.delete(task);
      else next.add(task);
      return next;
    });
  }
  function cell(row: Row, key: Column) {
    const data = values(row, now), value = data[key];
    if (key === "task") {
      if (row.earlier) return <button type="button" className="ml-2 text-accent hover:underline"
        onClick={() => onTask(data.task, false, data.try)}>Try {data.try}</button>;
      return <div className="grid gap-1">
        <button type="button" className="w-fit break-words text-left text-accent hover:underline" onClick={() => onTask(data.task)}>{data.task}</button>
        {row.task.attempts.length > 1 ? <button type="button" aria-expanded={expanded.has(data.task)}
          className="w-fit text-left text-xs text-muted hover:text-fg" onClick={() => toggle(data.task)}>
          <span aria-hidden>{expanded.has(data.task) ? "▾" : "▸"}</span> Earlier tries
        </button> : null}
      </div>;
    }
    if (key === "status") return <StatusBadge quiet status={data.status} />;
    if (value == null) return "—";
    if (key === "try") return value;
    if (typeof value !== "number") return value;
    if (key === "duration") return <MedianMark value={value} sample={row.task.duration} format={formatSeconds} />;
    if (key === "rejected" && !row.earlier && value > 0) return <button type="button" aria-label={`Reject breakdown for ${data.task}`} className="text-accent hover:underline" onClick={() => setRejectTask(data.task)}>{compactCount(value)}</button>;
    return formats[key](value);
  }
  if (stats.isError) return <Notice>{stats.error.message}</Notice>;
  if (stats.isPending) return <Loading what="run statistics" />;
  return <div className="grid min-w-0 gap-3">
    <div className="flex flex-wrap items-end gap-2 min-[480px]:hidden">
      <SelectField compact label="Sort statistics by" value={by} onChange={value => change(value as Column, false, 1)}>
        {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </SelectField>
      <Button onClick={() => change(by, !desc, 1)} aria-label={desc ? "Sort ascending" : "Sort descending"}>{desc ? "↓ Descending" : "↑ Ascending"}</Button>
    </div>
    <DataTable<Row> label="Run statistics" stacked multiline
      externalSort={{id: by, desc, change: (id, descending) => change(id as Column, descending, 1)}}
      data={pageRows} empty="No tasks recorded"
      columns={columnsOf<Row>((Object.keys(labels) as Column[]).map(id => ({
        id, header: labels[id], value: row => values(row, now)[id] ?? null, cell: row => cell(row, id),
      })))} />
    {pages > 1 ? <nav aria-label="Statistics pages" className="flex items-center gap-2">
      <Button disabled={page === 1} onClick={() => change(by, desc, page - 1)}>Previous</Button>
      <span aria-live="polite">Page {page} of {pages}</span>
      <Button disabled={page === pages} onClick={() => change(by, desc, page + 1)}>Next</Button>
    </nav> : null}
    {rejectTask ? <RejectBreakdown code={code} run={run} task={rejectTask} close={() => setRejectTask(null)} /> : null}
  </div>;
}

function RejectBreakdown({ code, run, task, close }: { code: string; run: RunView; task: string; close: () => void }) {
  const title = useId();
  const timezone = useTimezone();
  const result = useQuery({
    queryKey: ["reject-breakdown", code, run.pipeline_run_id, task],
    staleTime: 0,
    queryFn: () => getJson<Breakdown>(`${project(code)}/reject-breakdown`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, task_code: task }),
  });
  const data = result.data;
  return <Dialog open onClose={close} labelledBy={title}>
    <div className="grid gap-3 p-4">
      <h2 id={title} className="font-semibold">Reject breakdown · {task}</h2>
      {result.isPending ? <Loading what="reject breakdown" /> : null}
      {result.isError ? <Notice>{result.error.message}</Notice> : null}
      {data?.rows.length ? <ul>{data.rows.map(row => <li key={row.reason}>{row.reason} · {compactCount(row.count)}</li>)}</ul> : data ? <p>
        Reject breakdown unavailable.{data.reject_table && data.recorded_count > 0 ? <> This task recorded {data.recorded_count.toLocaleString("en-GB")} rejects; their rows are no longer in {data.reject_table}.</> : null}
        {data.retention_removed_at ? <> Retention last removed rows from this target on <time dateTime={data.retention_removed_at}>{formatTime(data.retention_removed_at, timezone)}</time>.</> : null}
      </p> : null}
      <Button className="justify-self-end" onClick={close}>Close</Button>
    </div>
  </Dialog>;
}
