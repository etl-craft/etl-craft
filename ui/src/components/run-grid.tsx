import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { GridTaskDetails } from "@/components/grid-task-details";
import { statusEntries, useLegend } from "@/components/legend";
import { AppLink as Link } from "@/components/navigation";
import { StatusMark, solidClass, statusMeta } from "@/components/status";
import { useNow } from "@/components/when";
import { useTimezone } from "@/hooks";
import { formatDuration, formatSeconds, formatTime } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { Graph, GridCell, RunView } from "@/lib/types";
import { cn } from "@/lib/utils";

export const DEFAULT_RUNS = 10;
export const MIN_TASKS = 126;
export const GRID_COLUMNS = { id: { width: 18, minimum: 18 }, time: { width: 18, minimum: 18 } };

export function RunGrid({ code, pipeline, graph, tasks, runs, cells, extra, selected, task, onSelect, bars = true }: {
  code: string; pipeline: string; graph: Graph; tasks: string[]; runs: RunView[]; cells: GridCell[];
  extra?: RunView; selected?: number; task?: string | null;
  onSelect: (runId: number, taskCode?: string) => void; bars?: boolean;
}) {
  const [definition, setDefinition] = useState<string | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const legend = useLegend(statusEntries([...runs.map(run => run.status), ...cells.map(cell => cell.status)]));
  useLayoutEffect(() => {
    const area = scroll.current;
    if (!area) return;
    const end = () => { area.scrollLeft = area.scrollWidth; };
    end();
    const observer = new ResizeObserver(end);
    observer.observe(area);
    return () => observer.disconnect();
  }, [runs.length]);
  const now = useNow();
  const timezone = useTimezone();
  const byRun = useMemo(() => new Map(cells.map((cell) => [JSON.stringify([cell.pipeline_run_id, cell.task_code]), cell])), [cells]);
  const shown = extra ? [...runs, extra].sort((a, b) => b.pipeline_run_id - a.pipeline_run_id).reverse() : [...runs].reverse();
  const durations = shown.map((run) => run.start_date
    ? Math.max(0, ((run.end_date ? Date.parse(run.end_date) : now) - Date.parse(run.start_date)) / 1000) : 0);
  const longest = Math.max(0, ...durations);
  return (
    <div tabIndex={0} className="relative flex h-full min-h-0 flex-col" onKeyDown={legend.onKeyDown}>
      {/* The key sits over the duration scale's empty corner instead of taking a row of its own. */}
      <div className="absolute right-2 top-1 z-30">{legend.button}</div>
      {legend.panel}
      <div ref={scroll} className="min-h-56 flex-1 overflow-auto scroll-pt-[100px]" data-scroll-area>
      <table aria-label="Run grid" className="w-max table-fixed border-separate border-spacing-0 text-xs">
        <thead className="sticky top-0 z-20 bg-surface">
          <tr>
            <th scope="col" className="sticky left-0 z-10 min-w-32 max-w-44 bg-surface px-2 text-left align-bottom">
              {bars && longest > 0 ? <div aria-label="Duration scale" className="grid h-[100px] content-between text-[10px] font-normal text-muted">
                <span>{formatSeconds(longest)}</span><span>{formatSeconds(longest / 2)}</span><span>0s</span>
              </div> : null}
              <span className="block h-5">Task</span>
            </th>
            {shown.map((run, index) => {
              const id = run.pipeline_run_id;
              const title = [`#${id}`, run.run_label, run.start_date && formatTime(run.start_date, timezone), formatDuration(run.start_date, run.end_date, now)].filter(Boolean).join(" · ");
              return <th scope="col" key={id} className="w-[18px] min-w-[18px] p-0 align-bottom">
                <Link to={runPath(code, pipeline, id)} title={title} aria-label={`Run ${title}`}
                  aria-current={id === selected && !task ? "true" : undefined}
                  onClick={(event) => { event.preventDefault(); onSelect(id); }}
                  className={cn("flex w-full flex-col items-center justify-end focus-visible:outline-accent", bars ? "h-[100px]" : "h-5")}>
                  {/* The bar's height is the run's duration against the longest loaded run; its number, time and duration are in the hover text. */}
                  {bars ? <span className={cn("relative flex w-[14px] items-end justify-center rounded-sm", solidClass(run.status))}
                    style={{ height: Math.max(14, longest ? (durations[index] ?? 0) / longest * 100 : 0) }}>
                    <StatusMark solid status={run.status} className="size-[14px] [&_svg]:size-[10px]" />
                  </span> : <StatusMark solid status={run.status} className="size-[14px] [&_svg]:size-[10px]" />}
                </Link>
              </th>;
            })}
          </tr>
        </thead>
        <tbody>
          {tasks.map((name) => <tr key={name} className="h-5">
            <th scope="row" title={name} className="sticky left-0 z-10 h-5 max-w-44 truncate border-t border-border bg-surface px-2 text-left font-medium">
              <button type="button" className="block w-full truncate text-left hover:underline"
                aria-label={`Task definition for ${name}`} onClick={() => setDefinition(name)}>{name}</button>
            </th>
            {shown.map(({ pipeline_run_id: id }) => {
              const cell = byRun.get(JSON.stringify([id, name]));
              const active = id === selected && name === task;
              return <td key={id} className="h-5 w-[18px] p-0 text-center">
                <button type="button" aria-pressed={active} title={cell ? statusMeta(cell.status).label : "Not started"}
                  aria-label={`${name} in run ${id}: ${cell ? statusMeta(cell.status).label.toLowerCase() : "not started"}`}
                  className={cn("mx-auto flex size-[18px] cursor-pointer items-center justify-center rounded-sm focus-visible:outline-2 focus-visible:outline-accent", active && "outline-2 -outline-offset-2 outline-accent")}
                  onClick={() => onSelect(id, name)}>
                  {cell ? <StatusMark solid status={cell.status} label={`${name} in run ${id}: ${statusMeta(cell.status).label.toLowerCase()}`} className="size-[14px] rounded-sm [&_svg]:size-[10px]" /> : <span aria-hidden className="text-muted">·</span>}
                </button>
              </td>;
            })}
          </tr>)}
        </tbody>
      </table>
      {shown.length === 0 ? <p className="p-2 text-sm text-muted">No runs yet.</p> : null}
      </div>
      <GridTaskDetails code={code} pipeline={pipeline} task={definition} graph={graph} onClose={() => setDefinition(null)} />
    </div>
  );
}

