import {LegendView,statusEntries} from "@/components/legend";
import { CirclePause, X } from "lucide-react";
import { DropdownMenu, DropdownTrigger, DropdownContent, DropdownItem } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { RunLabel } from "@/components/run-label";
import { When } from "@/components/when";
import * as React from "react";
import { AppLink as Link } from "@/components/navigation";
import { isFailure, solidClass, StatusBadge, StatusMark, statusMeta } from "@/components/status";
import { formatDuration } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { Pipeline, RunView } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Dense bars share one target; the chooser gives each recorded run its own full-size link. */
function RunChartMenu({project,runs,label,className,style,children}:{project:string;runs:(Pick<RunView,"pipeline_run_id"|"pipeline_code"|"status"> & Partial<Pick<RunView,"run_label"|"start_date"|"end_date">>)[];label:string;className?:string;style?:React.CSSProperties;children:React.ReactNode}) {
  return <DropdownMenu><DropdownTrigger asChild><Button data-run-chart variant="ghost" aria-label={label} title="Choose a run" style={style} className={cn("hit-target relative !h-auto min-h-6 min-w-6 !rounded-none !border-0 !bg-transparent !p-0 !justify-start",className)}>{children}</Button></DropdownTrigger><DropdownContent>
    {[...runs].sort((a,b)=>b.pipeline_run_id-a.pipeline_run_id).map(run=><DropdownItem key={run.pipeline_run_id} asChild><Link to={runPath(project,run.pipeline_code,run.pipeline_run_id)} aria-label={`Run #${run.pipeline_run_id}${run.run_label?` · ${run.run_label}`:""}, ${statusMeta(run.status).label}, ${formatDuration(run.start_date ?? null,run.end_date ?? null)}`}>
      <span className="min-w-0 flex-1"><RunLabel id={run.pipeline_run_id} label={run.run_label}/></span><StatusBadge status={run.status} quiet/>
    </Link></DropdownItem>)}
  </DropdownContent></DropdownMenu>;
}

/** A pipeline's newest runs as status marks with a chooser for inspecting any one. */
export function RecentRuns({ project, pipeline }: { project: string; pipeline: Pipeline }) {
  const runs = pipeline.recent_runs;
  if (runs.length === 0) return <span className="text-muted">No runs yet</span>;
  // Oldest first, so the newest run is at the right edge in the recent-run strip.
  const ordered = [...runs].sort((a, b) => a.pipeline_run_id - b.pipeline_run_id);
  const ok = runs.filter((r) => r.status === "SUCCESS").length;
  const failed = runs.filter((r) => isFailure(r.status)).length;
  // Bar height is the run's duration against the longest shown; a run without times is the shortest bar.
  const seconds = (r: (typeof runs)[number]) => (r.start_date && r.end_date ? Math.max(0, (new Date(r.end_date).getTime() - new Date(r.start_date).getTime()) / 1000) : 0);
  const longest = Math.max(1, ...ordered.map(seconds));
  return (
    <span className="flex items-center gap-2">
      <RunChartMenu project={project} runs={ordered.map(run=>({...run,pipeline_code:pipeline.pipeline_code}))} label={`Recent runs for ${pipeline.pipeline_code}`} style={{marginRight:Math.min(0,ordered.length*7-1-24)}}>
        <span aria-hidden className="flex h-5 items-end gap-px">
          {ordered.map(run=><span key={run.pipeline_run_id} style={{height:`${Math.round(4+(seconds(run)/longest)*16)}px`}} className={cn("w-1.5 rounded-xs",solidClass(run.status))}/>)}
        </span>
      </RunChartMenu>
      <RecentSummary latest={runs[0]!.status} failed={failed} ok={ok} total={runs.length} />
    </span>
  );
}

/**
 * The words beside the strip: the newest run's own symbol, then failures in red when there are any, so a
 * failing pipeline is found by reading down one column rather than by telling bar colours apart.
 */
function RecentSummary({ latest, failed, ok, total }: { latest: string; failed: number; ok: number; total: number }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap text-xs">
      <StatusMark status={latest} label={`Latest run: ${statusMeta(latest).label}`} className="size-4" />
      {failed ? (
        <span className="num inline-flex items-center gap-0.5 font-medium text-bad">
          <X aria-hidden className="size-3" strokeWidth={2.5} />
          {failed} failed
        </span>
      ) : (
        <span className="num text-muted">
          {ok}/{total} ok
        </span>
      )}
    </span>
  );
}

/** Whether automatic runs are on, and if not, who stopped them and why; a pause is slate, not a warning. */
export function PauseState({ pipeline }: { pipeline: Pipeline }) {
  const tasks = pipeline.task_pauses.length;
  if (!pipeline.paused)
    return (
      <span className="text-muted">
        Active
        {tasks ? <span className="text-fg"> · {tasks} task{tasks === 1 ? "" : "s"} paused</span> : null}
      </span>
    );
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-idle">
      <CirclePause aria-hidden className="size-4" />
      <span className="font-medium">Paused</span>
      <span className="text-muted">
        by {pipeline.paused.paused_by}: {pipeline.paused.reason}
      </span>
    </span>
  );
}

export function NextRun({ pipeline }: { pipeline: Pipeline }) {
  // "Not scheduled" is already said by the Schedule column beside this one.
  if (!pipeline.run_schedule) return <span className="text-muted">{pipeline.restart_note ?? "—"}</span>;
  if (pipeline.next_run) return <When iso={pipeline.next_run} />;
  // A pause is someone's decision (slate); a schedule that cannot produce a next run is a warning (amber).
  return pipeline.paused ? <span className="text-muted">Paused</span> : <span className="text-warn">{pipeline.schedule_problem ?? "No next run"}</span>;
}

export function TagList({ tags }: { tags: string[] }) {
  if (tags.length === 0) return <span className="text-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <span key={tag} className="rounded-sm bg-idle-bg px-1.5 py-0.5 text-xs text-idle">
          {tag}
        </span>
      ))}
    </span>
  );
}

/** Run durations, newest on the right, with the shared run chooser. */
export function RunBars({ project, runs }: { project: string; runs: Pick<RunView, "run_label" | "pipeline_run_id" | "pipeline_code" | "status" | "start_date" | "end_date">[] }) {
  const [now] = React.useState(() => Date.now());
  if (runs.length < 5) return null;
  const ordered = [...runs].reverse();
  const seconds = (run: (typeof runs)[number]) => (run.start_date ? Math.max(0, ((run.end_date ? new Date(run.end_date).getTime() : now) - new Date(run.start_date).getTime()) / 1000) : 0);
  const longest = Math.max(1, ...ordered.map(seconds));
  return (
    // Bars start at the left and keep their width, so a few runs read as a short strip, not a corner of an empty panel.
    <LegendView entries={statusEntries(ordered.map(run=>run.status),true)}><RunChartMenu project={project} runs={ordered} label="Run durations, newest on the right" className="w-full">
      <span aria-hidden className="m-0 flex h-20 w-full items-end justify-start gap-0.5 p-0">
        {ordered.map(run=><span key={run.pipeline_run_id} className="flex h-full w-3 min-w-1.5 shrink items-end"><span style={{height:`${Math.max(10,(seconds(run)/longest)*100)}%`}} className={cn("w-full rounded-xs",solidClass(run.status))}/></span>)}
      </span>
    </RunChartMenu></LegendView>
  );
}
