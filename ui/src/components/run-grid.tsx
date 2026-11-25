import { GridTaskDetails } from "@/components/grid-task-details";
import { Button } from "@/components/ui/button";
import { ChevronDown } from "lucide-react";
import {useLegend,statusEntries} from "@/components/legend";
import { RunLabel } from "@/components/run-label";
import { When } from "@/components/when";
import * as React from "react";
import { AppLink as Link } from "@/components/navigation";
import { StatusMark, solidClass, statusMeta } from "@/components/status";
import { formatDuration } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { Graph, GridCell, RunView } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How many of the newest runs the grid shows unless asked for more. */
export const DEFAULT_RUNS = 25;
export const MIN_TASKS = 96;
export const GRID_COLUMNS = { id: { width: 28, minimum: 30 }, time: { width: 176, minimum: 178 } };

/**
 * Every task against the pipeline's recent runs, newest on the right, like the duration bars above it: one glance shows where and when a task
 * started failing. A column header selects a run; a cell selects the run and opens that task in it.
 */
export function RunGrid({ code, pipeline, graph, runs, cells, extra, selected, onSelect, bars = true, labels = "id" }: { code: string; pipeline: string; graph: Graph; runs: RunView[]; cells: GridCell[]; extra?: RunView; selected?: number; onSelect: (runId: number, task?: string) => void; bars?: boolean; labels?: "id" | "time" }) {
  const [details,setDetails]=React.useState<string|null>(null);
  const cell = GRID_COLUMNS[labels].width;
  const reserve = GRID_COLUMNS[labels].minimum;
  const tasks = graph.waves.flat();
  const latest = runs;
  // A run opened by a link that is older than the newest ones shown still has its column, set apart from them.
  const shown = [...latest, ...(extra && !latest.some((r) => r.pipeline_run_id === extra.pipeline_run_id) ? [extra] : [])].sort((a, b) => a.pipeline_run_id - b.pipeline_run_id);
  const showBars = bars && shown.length >= 5;
  const apart = (run: RunView) => extra !== undefined && run.pipeline_run_id === extra.pipeline_run_id && !latest.some((r) => r.pipeline_run_id === run.pipeline_run_id);
  const box = React.useRef<HTMLDivElement>(null);
  const outer = React.useRef<HTMLDivElement>(null);
  const hasRuns = shown.length > 0;
  // The task column is as wide as the longest task code, up to this much of the pane: it gives way only so far.
  const [room, setRoom] = React.useState(0);
  const [gutter, setGutter] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = outer.current;
    if (!element) return;
    const measure = () => {
      setRoom(Math.max(0, element.clientWidth - 6));
      setGutter(box.current ? box.current.offsetWidth - box.current.clientWidth : 0);
    };
    measure();
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watch?.observe(element);
    if (box.current) watch?.observe(box.current);
    return () => watch?.disconnect();
  }, [hasRuns]);
  const head = React.useRef<HTMLDivElement>(null);
  const [natural, setNatural] = React.useState(128);
  React.useLayoutEffect(() => {
    const measure = () => setNatural(Math.max(128, ...Array.from(head.current?.querySelectorAll("tbody th span") ?? [], (name) => Math.ceil(name.scrollWidth) + 40)));
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    head.current?.querySelectorAll("tbody th span").forEach((name) => observer?.observe(name));
    return () => observer?.disconnect();
  }, [graph, hasRuns]);
  const taskWidth = Math.max(MIN_TASKS, Math.min(natural, hasRuns ? room - reserve - gutter : room));
  const matrixWidth = Math.max(0, Math.min(room - taskWidth, shown.length * cell + 2 + gutter));
  const [bar, setBar] = React.useState(0);
  // A run chosen from elsewhere is brought into view.
  React.useEffect(() => {
    box.current?.querySelector("[aria-current=true]")?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [selected]);
  const byRun = React.useMemo(() => {
    const entries = new Map<number, Map<string, GridCell>>();
    for (const entry of cells) {
      let tasks = entries.get(entry.pipeline_run_id);
      if (!tasks) {
        tasks = new Map();
        entries.set(entry.pipeline_run_id, tasks);
      }
      tasks.set(entry.task_code, entry);
    }
    return entries;
  }, [cells]);
  const [now] = React.useState(() => Date.now());
  const seconds = (run: RunView) => (run.start_date ? Math.max(0, ((run.end_date ? new Date(run.end_date).getTime() : now) - new Date(run.start_date).getTime()) / 1000) : 0);
  const longest = Math.max(1, ...shown.map(seconds));
  const key = useLegend(statusEntries([
    ...shown.map((run) => run.status),
    ...shown.flatMap((run) => [...(byRun.get(run.pipeline_run_id)?.values() ?? [])].map((cell) => cell.status)),
  ]));
  const sync = () => {
    if (head.current && box.current) {
      head.current.scrollTop = box.current.scrollTop;
      setBar(box.current.offsetHeight - box.current.clientHeight);
    }
  };
  const tall = showBars ? "h-20" : "h-0";
  const open = (run: RunView) => (event: React.MouseEvent) => {
    event.preventDefault();
    onSelect(run.pipeline_run_id);
  };
  return (
    <div ref={outer} tabIndex={0} onKeyDown={key.onKeyDown} className="relative flex h-full min-h-0 w-full flex-col"><div className="flex justify-end px-2 py-1">{key.button}</div>{key.panel}
      <div className="flex min-h-0 flex-1">
        <div style={{ width: taskWidth }} className="flex shrink-0 flex-col">
          {/* The task list scrolls with the matrix and has no scroll bar of its own. */}
          <div ref={head} onWheel={(e) => box.current && (box.current.scrollTop += e.deltaY)} style={{ paddingBottom: bar }} className="min-h-0 flex-1 overflow-hidden">
            <table aria-label="Tasks" className="w-full table-fixed border-separate border-spacing-0 text-[13px]">
              <thead>
                {showBars ? (
                  <tr>
                    <th scope="col" className="sticky top-0 z-20 h-20 bg-surface px-3 text-left align-bottom text-xs font-medium text-muted">Duration</th>
                  </tr>
                ) : null}
                <tr>
                  <th scope="col" className={cn("sticky z-20 bg-surface-2 px-3 text-left text-xs font-medium text-muted", labels === "time" ? "h-10" : "h-7", showBars ? "top-20" : "top-0")}>Task</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task}>
                    <th scope="row" className="h-8 truncate border-t border-border bg-surface px-3 py-0 text-left font-medium" title={task}>
                      <Button size="sm" variant="ghost" className="!h-8 w-full justify-between gap-1 !px-0" aria-label={`Task definition for ${task}`} onClick={()=>setDetails(task)}><span className="inline-block truncate">{task}</span><ChevronDown aria-hidden className="size-3 shrink-0"/></Button>
                    </th>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div aria-hidden className="w-1.5 shrink-0 border-l border-border-strong" />
        {/* The right scroll origin keeps the newest run visible as the pane narrows. */}
        {!hasRuns?<p className="m-0 p-4 text-muted">No runs yet.</p>:null}
        <div ref={box} dir="rtl" onScroll={sync} style={{ width: matrixWidth, minWidth: 0 }} className="min-h-0 shrink-0 overflow-auto">
          <div dir="ltr" className="w-max">
            <table aria-label="Run grid" style={{ width: shown.length * cell }} className="table-fixed border-separate border-spacing-0 text-[13px]">
              <thead>
                {showBars ? (
                  <tr>
                    {shown.map((run) => (
                      <td key={run.pipeline_run_id} className={cn("sticky top-0 z-10 px-0 align-bottom", tall, apart(run) && "border-l-2 border-dashed border-border-strong", run.pipeline_run_id === selected ? "bg-fg/10" : "bg-surface")}>
                        <div className="flex h-full items-end justify-center pb-0.5">
                          <Link
                            to={runPath(code, pipeline, run.pipeline_run_id)}
                            onClick={open(run)}
                            title={`Run ${run.pipeline_run_id}${run.run_label ? ` · ${run.run_label}` : ""} · ${statusMeta(run.status).label} · ${formatDuration(run.start_date, run.end_date)}`}
                            aria-label={`Run ${run.pipeline_run_id}${run.run_label ? ` · ${run.run_label}` : ""}, ${statusMeta(run.status).label}, ${formatDuration(run.start_date, run.end_date)}`}
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
                    <th key={run.pipeline_run_id} scope="col" className={cn("sticky z-10 px-0 text-center text-xs font-medium", labels === "time" ? "h-10" : "h-7", showBars ? "top-20" : "top-0", apart(run) && "border-l-2 border-dashed border-border-strong", run.pipeline_run_id === selected ? "bg-fg/10 text-fg" : "bg-surface-2 text-muted")}>
                      <Link className="num hover:text-accent hover:underline" to={runPath(code, pipeline, run.pipeline_run_id)} onClick={open(run)} aria-current={run.pipeline_run_id === selected ? "true" : undefined}>
                        <RunLabel id={run.pipeline_run_id} label={run.run_label} compact />
                        {labels === "time" && run.start_date ? <span className="block truncate text-[9px]"><When iso={run.start_date} /></span> : null}
                      </Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task}>
                    {shown.map((run) => {
                      const entry = byRun.get(run.pipeline_run_id)?.get(task);
                      const chosen = run.pipeline_run_id === selected;
                      return (
                        <td key={run.pipeline_run_id} className={cn("h-8 border-l border-t border-border px-0 py-0 text-center align-middle", apart(run) && "border-l-2 border-dashed border-l-border-strong", chosen && "bg-fg/10")}>
                          {entry ? (
                            <button type="button" title={`${run.run_label ?? ""} · ${entry.task_run_label ?? ""}`} className="inline-grid cursor-pointer rounded-sm hover:ring-2 hover:ring-accent" onClick={() => onSelect(run.pipeline_run_id, task)}>
                              <StatusMark solid className="size-6" status={entry.status} label={`${task} in run ${run.pipeline_run_id}: ${entry.status.toLowerCase()}`} />
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
      <GridTaskDetails code={code} pipeline={pipeline} task={details} graph={graph} onClose={()=>setDetails(null)}/>
    </div>
  );
}
