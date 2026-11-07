import { useQueries } from "@tanstack/react-query";
import * as React from "react";
import { Link } from "react-router-dom";
import { Loading, Notice } from "@/components/common";
import { StatusMark, statusMeta, toneClass } from "@/components/status";
import { formatDuration } from "@/lib/format";
import { getJson, project } from "@/lib/api";
import { runPath } from "@/lib/routes";
import type { Graph, RunView, TaskHistory } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLUMNS = 25;

/**
 * Every task against the pipeline's recent runs, newest on the right, like the duration bars above it: one glance shows where and when a task
 * started failing. A column header selects a run; a cell selects the run and opens that task in it.
 */
export function RunGrid({ code, pipeline, graph, runs, selected, onSelect }: { code: string; pipeline: string; graph: Graph; runs: RunView[]; selected?: number; onSelect: (runId: number, task?: string) => void }) {
  const tasks = graph.waves.flat();
  const latest = runs.slice(0, COLUMNS);
  const newest = latest[0]?.pipeline_run_id;
  const shown = [...latest].reverse();
  const cells = useQueries({
    queries: tasks.map((task) => ({
      queryKey: ["matrix", code, pipeline, task, newest, latest.length],
      enabled: newest !== undefined,
      queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, task_code: task, all: true, limit: latest.length, before: (newest ?? 0) + 1 }),
    })),
  });
  const [now] = React.useState(() => Date.now());
  const seconds = (run: RunView) => (run.start_date ? Math.max(0, ((run.end_date ? new Date(run.end_date).getTime() : now) - new Date(run.start_date).getTime()) / 1000) : 0);
  const longest = Math.max(1, ...shown.map(seconds));
  if (shown.length === 0) return <p className="m-0 p-4 text-muted">No runs yet.</p>;
  const failed = cells.find((c) => c.isError);
  return (
    <>
      {failed?.error ? <Notice className="m-3">{(failed.error as Error).message}</Notice> : null}
      {cells.some((c) => c.isPending) ? <Loading what="the grid" className="p-3" /> : null}
      <table aria-label="Run grid" className="w-full border-separate border-spacing-0 text-[13px]">
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 top-0 z-20 h-20 bg-surface px-3 text-left align-bottom text-xs font-medium text-muted">
              Duration
            </th>
            {shown.map((run) => (
              <td key={run.pipeline_run_id} className={cn("sticky top-0 z-10 h-20 px-0.5 align-bottom", run.pipeline_run_id === selected ? "bg-accent/10" : "bg-surface")}>
                <div className="flex h-full items-end justify-center pb-1">
                  <Link
                    to={runPath(code, pipeline, run.pipeline_run_id)}
                    onClick={(event) => {
                      event.preventDefault();
                      onSelect(run.pipeline_run_id);
                    }}
                    title={`Run ${run.pipeline_run_id} · ${statusMeta(run.status).label} · ${formatDuration(run.start_date, run.end_date)}`}
                    aria-label={`Run ${run.pipeline_run_id}, ${statusMeta(run.status).label}, ${formatDuration(run.start_date, run.end_date)}`}
                    style={{ height: `${Math.max(10, (seconds(run) / longest) * 100)}%` }}
                    className={cn("w-4 rounded-sm border border-current opacity-90 hover:opacity-100", toneClass(run.status))}
                  />
                </div>
              </td>
            ))}
          </tr>
          <tr>
            <th scope="col" className="sticky left-0 top-20 z-20 bg-surface-2 px-3 py-1.5 text-left text-xs font-medium text-muted">
              Task
            </th>
            {shown.map((run) => (
              <th key={run.pipeline_run_id} scope="col" className={cn("sticky top-20 z-10 px-0.5 py-1.5 text-center text-xs font-medium", run.pipeline_run_id === selected ? "bg-accent/15 text-fg" : "bg-surface-2 text-muted")}>
                <Link
                  className="num hover:text-accent hover:underline"
                  to={runPath(code, pipeline, run.pipeline_run_id)}
                  onClick={(event) => {
                    event.preventDefault();
                    onSelect(run.pipeline_run_id);
                  }}
                  aria-current={run.pipeline_run_id === selected ? "true" : undefined}
                >
                  {run.pipeline_run_id}
                </Link>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task, row) => (
            <tr key={task}>
              <th scope="row" className="sticky left-0 z-10 max-w-48 truncate border-t border-border bg-surface px-3 py-0.5 text-left font-medium" title={task}>
                {task}
              </th>
              {shown.map((run) => {
                const entry = cells[row]?.data?.entries.find((e) => e.pipeline_run_id === run.pipeline_run_id);
                const chosen = run.pipeline_run_id === selected;
                return (
                  <td key={run.pipeline_run_id} className={cn("border-t border-border px-0.5 py-0.5 text-center", chosen && "bg-accent/10")}>
                    {entry ? (
                      <button type="button" className="inline-grid cursor-pointer rounded-full hover:ring-2 hover:ring-accent" onClick={() => onSelect(run.pipeline_run_id, task)}>
                        <StatusMark className="size-5" status={entry.status} label={`${task} in run ${run.pipeline_run_id}: ${entry.status.toLowerCase()}`} />
                      </button>
                    ) : (
                      <span className="text-muted" aria-label={`${task} did not start in run ${run.pipeline_run_id}`}>
                        ·
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
