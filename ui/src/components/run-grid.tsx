import { When } from "@/components/when";
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
export const MIN_TASKS = 96;
export const GRID_COLUMNS = { id: { width: 24, minimum: 26 }, time: { width: 176, minimum: 178 } };

/**
 * Every task against the pipeline's recent runs, newest on the right, like the duration bars above it: one glance shows where and when a task
 * started failing. A column header selects a run; a cell selects the run and opens that task in it.
 */
export function RunGrid({ code, pipeline, graph, runs, extra, selected, onSelect, bars = true, labels = "id", pane }: { code: string; pipeline: string; graph: Graph; runs: RunView[]; extra?: RunView; selected?: number; onSelect: (runId: number, task?: string) => void; bars?: boolean; labels?: "id" | "time"; pane?: { maximum: number; resize: (width: number) => void } }) {
  const cell = GRID_COLUMNS[labels].width;
  const reserve = GRID_COLUMNS[labels].minimum;
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
  const [room, setRoom] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = outer.current;
    if (!element) return;
    const measure = () => setRoom(Math.max(0, element.clientWidth - 6));
    measure();
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watch?.observe(element);
    return () => watch?.disconnect();
  }, [hasRuns]);
  const head = React.useRef<HTMLDivElement>(null);
  const [natural, setNatural] = React.useState(128);
  React.useLayoutEffect(() => {
    const measure = () => setNatural(Math.max(128, ...Array.from(head.current?.querySelectorAll("tbody th span") ?? [], (name) => Math.ceil(name.getBoundingClientRect().width) + 24)));
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    head.current?.querySelectorAll("tbody th span").forEach((name) => observer?.observe(name));
    return () => observer?.disconnect();
  }, [graph, hasRuns]);
  const [wanted, setWanted] = React.useState<number | null>(null);
  const maximum = Math.max(MIN_TASKS, Math.min(natural, (pane?.maximum || room + 6) - 6 - reserve));
  const taskWidth = Math.max(MIN_TASKS, Math.min(wanted ?? Math.min(natural, Math.max(128, room * 0.45)), natural, room - reserve));
  const matrixWidth = Math.max(0, Math.min(room - taskWidth, shown.length * cell + 2));
  const resizeTasks = (next: number) => {
    const width = Math.max(MIN_TASKS, Math.min(maximum, next));
    if (width > taskWidth && width + reserve > room) pane?.resize(width + 6 + reserve);
    else if (width < taskWidth && room <= taskWidth + reserve + 1) pane?.resize(room + 6 + width - taskWidth);
    setWanted(width);
  };
  const start = React.useRef<{ x: number; width: number } | null>(null);
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
                      <span className="inline-block">{task}</span>
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
          aria-label="Resize task names"
          aria-valuemin={MIN_TASKS}
          aria-valuemax={Math.round(maximum)}
          aria-valuenow={Math.round(taskWidth)}
          aria-valuetext={`${Math.round(taskWidth)} pixels`}
          className="group relative w-1.5 shrink-0 cursor-col-resize touch-none outline-none"
          onPointerDown={(event) => {
            event.preventDefault();
            start.current = { x: event.clientX, width: taskWidth };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (start.current && event.currentTarget.hasPointerCapture(event.pointerId)) resizeTasks(start.current.width + event.clientX - start.current.x);
          }}
          onLostPointerCapture={() => { start.current = null; }}
          onDoubleClick={() => resizeTasks(natural)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
              event.preventDefault();
              resizeTasks(taskWidth + (event.key === "ArrowRight" ? 16 : -16));
            } else if (event.key === "Home" || event.key === "End") {
              event.preventDefault();
              resizeTasks(event.key === "Home" ? MIN_TASKS : natural);
            }
          }}
        >
          <span aria-hidden className="absolute inset-y-0 left-0.5 w-px bg-border-strong group-hover:w-0.5 group-hover:bg-accent group-focus-visible:bg-accent" />
        </div>
        {/* Right to left, so the scroll origin is the right edge: the newest run stays in view as the matrix narrows, and the oldest runs are the ones that scroll away. */}
        <div ref={box} dir="rtl" onScroll={sync} style={{ width: matrixWidth, minWidth: 0 }} className="min-h-0 shrink-0 overflow-auto">
          <div dir="ltr" className="w-max">
            <table aria-label="Run grid" style={{ width: shown.length * cell }} className="table-fixed border-separate border-spacing-0 text-[13px]">
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
                        {labels === "time" && run.start_date ? <span className="block truncate"><When iso={run.start_date} /></span> : run.pipeline_run_id}
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
                              <StatusMark solid className="size-5" status={entry.status} label={`${task} in run ${run.pipeline_run_id}: ${entry.status.toLowerCase()}`} />
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
