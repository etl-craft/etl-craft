import { CirclePause } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { solidClass, statusMeta } from "@/components/status";
import { formatDuration, formatTime } from "@/lib/format";
import { runPath } from "@/lib/routes";
import type { Pipeline, RunView } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A pipeline's newest runs as status marks; each opens its run. */
export function RecentRuns({ project, pipeline }: { project: string; pipeline: Pipeline }) {
  const runs = pipeline.recent_runs;
  if (runs.length === 0) return <span className="text-muted">No runs yet</span>;
  // Oldest first, so the newest run is at the right edge like the grid's.
  const ordered = [...runs].sort((a, b) => a.pipeline_run_id - b.pipeline_run_id);
  const ok = runs.filter((r) => r.status === "SUCCESS").length;
  return (
    <span className="flex items-center gap-2">
      <span role="list" aria-label="Recent runs, newest on the right" className="flex items-end gap-px">
        {ordered.map((run) => (
          <Link
            key={run.pipeline_run_id}
            role="listitem"
            to={runPath(project, pipeline.pipeline_code, run.pipeline_run_id)}
            aria-label={`Run ${run.pipeline_run_id}, ${statusMeta(run.status).label}`}
            title={`Run ${run.pipeline_run_id}: ${statusMeta(run.status).label}`}
            className={cn("h-4 w-1.5 rounded-xs hover:brightness-110", solidClass(run.status))}
          />
        ))}
      </span>
      <span className="num text-xs text-muted">
        {ok}/{runs.length} ok
      </span>
    </span>
  );
}

/** Whether automatic runs are on, and if not, who stopped them and why. */
export function PauseState({ pipeline }: { pipeline: Pipeline }) {
  const tasks = pipeline.task_pauses.length;
  if (!pipeline.paused)
    return (
      <span className="text-muted">
        Active
        {tasks ? <span className="text-warn"> · {tasks} task{tasks === 1 ? "" : "s"} paused</span> : null}
      </span>
    );
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-warn">
      <CirclePause aria-hidden className="size-4" />
      <span className="font-medium">Paused</span>
      <span className="text-muted">
        by {pipeline.paused.paused_by}: {pipeline.paused.reason}
      </span>
    </span>
  );
}

export function NextRun({ pipeline, timeZone }: { pipeline: Pipeline; timeZone: string }) {
  if (!pipeline.run_schedule) return <span className="text-muted">{pipeline.restart_note ?? "Not scheduled"}</span>;
  if (pipeline.next_run) return <span className="num whitespace-nowrap">{formatTime(pipeline.next_run, timeZone)}</span>;
  return <span className="text-warn">{pipeline.paused ? "Paused" : (pipeline.schedule_problem ?? "No next run")}</span>;
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

/** Run durations, newest on the right; each bar opens its run. */
export function RunBars({ project, runs }: { project: string; runs: RunView[] }) {
  const [now] = React.useState(() => Date.now());
  const ordered = [...runs].reverse();
  const seconds = (run: RunView) => (run.start_date ? Math.max(0, ((run.end_date ? new Date(run.end_date).getTime() : now) - new Date(run.start_date).getTime()) / 1000) : 0);
  const longest = Math.max(1, ...ordered.map(seconds));
  return (
    <ul className="m-0 flex h-20 list-none items-end justify-end gap-0.5 p-0" aria-label="Run durations, newest on the right">
      {ordered.map((run) => (
        <li key={run.pipeline_run_id} className="flex h-full min-w-1.5 max-w-3 flex-1 items-end">
          <Link
            to={runPath(project, run.pipeline_code, run.pipeline_run_id)}
            title={`Run ${run.pipeline_run_id} · ${statusMeta(run.status).label} · ${formatDuration(run.start_date, run.end_date)}`}
            aria-label={`Run ${run.pipeline_run_id}, ${statusMeta(run.status).label}, ${formatDuration(run.start_date, run.end_date)}`}
            style={{ height: `${Math.max(10, (seconds(run) / longest) * 100)}%` }}
            className={cn("w-full rounded-xs hover:brightness-110", solidClass(run.status))}
          />
        </li>
      ))}
    </ul>
  );
}
