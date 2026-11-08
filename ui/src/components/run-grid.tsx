import { useQueries } from "@tanstack/react-query";
import * as React from "react";
import { Link } from "react-router-dom";
import { Loading, Notice } from "@/components/common";
import { StatusMark, solidClass, statusMeta } from "@/components/status";
import { formatDuration } from "@/lib/format";
import { getJson, project } from "@/lib/api";
import { runPath } from "@/lib/routes";
import type { Graph, RunView, TaskHistory } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How many of the newest runs the grid shows unless asked for more. */
export const DEFAULT_RUNS = 25;
const CELL = 20;
const MIN_TASKS = 96;
const MIN_MATRIX = 60;

/**
 * Every task against the pipeline's recent runs, newest on the right, like the duration bars above it: one glance shows where and when a task
 * started failing. A column header selects a run; a cell selects the run and opens that task in it.
 */
export function RunGrid({ code, pipeline, graph, runs, extra, selected, onSelect, bars = true, labels = "id" }: { code: string; pipeline: string; graph: Graph; runs: RunView[]; extra?: RunView; selected?: number; onSelect: (runId: number, task?: string) => void; bars?: boolean; labels?: "id" | "time" }) {
  const tasks = graph.waves.flat();
  const latest = runs;
  const newest = latest[0]?.pipeline_run_id;
  // A run opened by a link that is older than the newest ones shown still has its column, set apart from them.
  const shown = [...latest, ...(extra && !latest.some((r) => r.pipeline_run_id === extra.pipeline_run_id) ? [extra] : [])].sort((a, b) => a.pipeline_run_id - b.pipeline_run_id);
  const apart = (run: RunView) => extra !== undefined && run.pipeline_run_id === extra.pipeline_run_id && !latest.some((r) => r.pipeline_run_id === run.pipeline_run_id);
  const box = React.useRef<HTMLDivElement>(null);
  const outer = React.useRef<HTMLDivElement>(null);
  const hasRuns = shown.length > 0;
  // The task column is as wide as the longest task code, up to this much of the pane: it gives way only so far.
  const [pane, setPane] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = outer.current;
    if (!element) return;
    const measure = () => setPane(Math.max(0, element.clientWidth - 6));
    measure();
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watch?.observe(element);
    return () => watch?.disconnect();
  }, [hasRuns]);
  // The task list and the matrix are one object: the divider between them moves both, and narrowing the pane narrows both, so each shows part of itself.
  const widest = Math.max(...tasks.map((t) => t.length), 4);
  const [share, setShare] = React.useState<number | null>(null);
  const natural = Math.round(widest * 7.4 + 28);
  const matrixWanted = shown.length * CELL;
  const autoTasks = Math.round(Math.min(Math.max(natural, 128), Math.max(128, pane * 0.45)));
  // With room to spare the task list takes it, so the last run sits against the pane's edge.
  const taskWidth = share === null ? Math.max(autoTasks, Math.min(pane - matrixWanted, natural + 400)) : Math.round(Math.min(Math.max(share * pane, MIN_TASKS), Math.max(MIN_TASKS, pane - MIN_MATRIX)));
  const matrixWidth = Math.max(0, pane - taskWidth);
  const head = React.useRef<HTMLDivElement>(null);
  const [bar, setBar] = React.useState(0);
  // A run chosen from elsewhere is brought into view.
  React.useEffect(() => {
    box.current?.querySelector("[aria-current=true]")?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [selected]);
  const aside = useQueries({
    queries: tasks.map((task) => ({
      queryKey: ["matrix-run", code, pipeline, task, extra?.pipeline_run_id],
      enabled: extra !== undefined && shown.some(apart),
      queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, task_code: task, run_id: extra?.pipeline_run_id }),
    })),
  });
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
  const sync = () => {
    if (head.current && box.current) {
      head.current.scrollTop = box.current.scrollTop;
      setBar(box.current.offsetHeight - box.current.clientHeight);
    }
  };
  const drag = (event: React.PointerEvent) => {
    event.preventDefault();
    const from = event.clientX;
    const start = taskWidth;
    const move = (e: PointerEvent) => setShare((start + e.clientX - from) / Math.max(1, pane));
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };
  const tall = bars ? "h-20" : "h-0";
  const open = (run: RunView) => (event: React.MouseEvent) => {
    event.preventDefault();
    onSelect(run.pipeline_run_id);
  };
  return (
    <div ref={outer} className="flex h-full min-h-0 w-full flex-col">
      {failed?.error ? <Notice className="m-3">{(failed.error as Error).message}</Notice> : null}
      {cells.some((c) => c.isPending) ? <Loading what="the grid" className="p-3" /> : null}
      <div className="flex min-h-0 flex-1">
        <div style={{ width: taskWidth }} className="flex shrink-0 flex-col">
          {/* The task list scrolls with the matrix and has no scroll bar of its own. */}
          <div ref={head} onWheel={(e) => box.current && (box.current.scrollTop += e.deltaY)} style={{ paddingBottom: bar }} className="min-h-0 flex-1 overflow-hidden">
            <table aria-label="Tasks" className="w-full table-fixed border-separate border-spacing-0 text-[13px]">
              <thead>
                {bars ? (
                  <tr>
                    <th scope="col" className="sticky top-0 z-20 h-20 bg-surface px-3 text-left align-bottom text-xs font-medium text-muted">Duration</th>
                  </tr>
                ) : null}
                <tr>
                  <th scope="col" className={cn("sticky z-20 h-7 bg-surface-2 px-3 text-left text-xs font-medium text-muted", bars ? "top-20" : "top-0")}>Task</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task}>
                    <th scope="row" className="h-7 truncate border-t border-border bg-surface px-3 py-0 text-left font-medium" title={task}>
                      {task}
                    </th>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div
          role="separator"
          tabIndex={0}
          aria-orientation="vertical"
          aria-label="Resize the task list and the runs"
          aria-valuenow={Math.round(taskWidth)}
          className="group relative w-1.5 shrink-0 cursor-col-resize touch-none outline-none"
          onPointerDown={drag}
          onDoubleClick={() => setShare(null)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              setShare((taskWidth + (event.key === "ArrowRight" ? 16 : -16)) / Math.max(1, pane));
            }
          }}
        >
          <span aria-hidden className="absolute inset-y-0 left-0.5 w-px bg-border-strong group-hover:w-0.5 group-hover:bg-accent group-focus-visible:bg-accent" />
        </div>
        {/* Right to left, so the scroll origin is the right edge: the newest run stays in view as the matrix narrows, and the oldest runs are the ones that scroll away. */}
        <div ref={box} dir="rtl" onScroll={sync} style={{ width: matrixWidth, minWidth: 0 }} className="min-h-0 flex-1 overflow-auto">
          <div dir="ltr" className="w-max">
            <table aria-label="Run grid" style={{ width: shown.length * CELL }} className="table-fixed border-separate border-spacing-0 text-[13px]">
              <thead>
                {bars ? (
                  <tr>
                    {shown.map((run) => (
                      <td key={run.pipeline_run_id} className={cn("sticky top-0 z-10 px-0 align-bottom", tall, apart(run) && "border-l-2 border-dashed border-border-strong", run.pipeline_run_id === selected ? "bg-accent/10" : "bg-surface")}>
                        <div className="flex h-full items-end justify-center pb-0.5">
                          <Link
                            to={runPath(code, pipeline, run.pipeline_run_id)}
                            onClick={open(run)}
                            title={`Run ${run.pipeline_run_id} · ${statusMeta(run.status).label} · ${formatDuration(run.start_date, run.end_date)}`}
                            aria-label={`Run ${run.pipeline_run_id}, ${statusMeta(run.status).label}, ${formatDuration(run.start_date, run.end_date)}`}
                            style={{ height: `${Math.max(10, (seconds(run) / longest) * 100)}%` }}
                            className={cn("w-3 rounded-xs hover:brightness-110", solidClass(run.status))}
                          />
                        </div>
                      </td>
                    ))}
                  </tr>
                ) : null}
                <tr>
                  {shown.map((run) => (
                    <th key={run.pipeline_run_id} scope="col" className={cn("sticky z-10 h-7 px-0 text-center text-xs font-medium", bars ? "top-20" : "top-0", apart(run) && "border-l-2 border-dashed border-border-strong", run.pipeline_run_id === selected ? "bg-accent/15 text-fg" : "bg-surface-2 text-muted")}>
                      <Link className="num hover:text-accent hover:underline" to={runPath(code, pipeline, run.pipeline_run_id)} onClick={open(run)} aria-current={run.pipeline_run_id === selected ? "true" : undefined}>
                        {labels === "time" && run.start_date ? new Date(run.start_date).toISOString().slice(5, 16).replace("T", " ") : run.pipeline_run_id}
                      </Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tasks.map((task, row) => (
                  <tr key={task}>
                    {shown.map((run) => {
                      const entry = (apart(run) ? aside[row] : cells[row])?.data?.entries.find((e) => e.pipeline_run_id === run.pipeline_run_id);
                      const chosen = run.pipeline_run_id === selected;
                      return (
                        <td key={run.pipeline_run_id} className={cn("h-7 border-l border-t border-border px-0 py-0 text-center align-middle", apart(run) && "border-l-2 border-dashed border-l-border-strong", chosen && "bg-accent/10")}>
                          {entry ? (
                            <button type="button" className="inline-grid cursor-pointer rounded-sm hover:ring-2 hover:ring-accent" onClick={() => onSelect(run.pipeline_run_id, task)}>
                              <StatusMark solid className="size-4" status={entry.status} label={`${task} in run ${run.pipeline_run_id}: ${entry.status.toLowerCase()}`} />
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
          </div>
        </div>
      </div>
    </div>
  );
}
