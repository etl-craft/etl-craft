import * as React from "react";
import { statusMeta, statusSolid } from "@/components/status";
import { useNow } from "@/components/when";
import { useTimezone } from "@/hooks";
import { formatDuration, formatTime } from "@/lib/format";
import type { RunView, TimelineKind, TimelineSegment } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Each kind keeps its own pattern, so a wait never reads as work: only execution is a solid status bar. */
const KIND: Record<TimelineKind, { label: string; className: string; spoken?: string }> = {
  QUEUE: { label: "Queued for a slot", className: "timeline-queue" },
  GATE: { label: "Dependency gate", className: "timeline-gate" },
  EVENT: { label: "Event wait", className: "timeline-event" },
  CHILD_RUN: { label: "Child run wait", className: "timeline-child" },
  EXECUTION: { label: "Attempt (status colour)", className: "timeline-attempt", spoken: "Running" },
};

const PIPELINE_ROW = "Pipeline gate";

function describe(segment: TimelineSegment, tz: string, open: boolean): string {
  const who = segment.task_code ?? "Pipeline";
  const attempt = segment.attempt_number ? `, attempt ${segment.attempt_number}` : "";
  const end = segment.ended_at ? formatTime(segment.ended_at, tz) : open ? "still open" : "stopped with the run";
  const lasted = segment.ended_at ? `, ${formatDuration(segment.started_at, segment.ended_at)}` : "";
  const deadline = segment.deadline ? `, deadline ${formatTime(segment.deadline, tz)}` : "";
  return `${who}${attempt}: ${KIND[segment.kind].spoken ?? KIND[segment.kind].label} from ${formatTime(segment.started_at, tz)} to ${end}${lasted}${deadline}. ${statusMeta(segment.outcome).label}.`;
}

function compactSegments(timeline: TimelineSegment[]): TimelineSegment[] {
  const tasks = new Map<string, TimelineSegment[]>();
  for (const segment of timeline) {
    if (segment.task_code === null) continue;
    const entries = tasks.get(segment.task_code) ?? [];
    entries.push(segment);
    tasks.set(segment.task_code, entries);
  }
  return [...tasks.values()].flatMap(entries => {
    const work = entries.filter(segment => segment.kind === "EXECUTION");
    const first = work[0];
    const last = work.at(-1);
    if (!first || !last) return entries.filter(segment => segment.kind === "QUEUE").slice(0, 1);
    const queued = entries.find(segment => segment.kind === "QUEUE" && segment.started_at < first.started_at);
    const merged = { ...last, started_at: first.started_at };
    return queued ? [{ ...queued, ended_at: first.started_at }, merged] : [merged];
  });
}

/**
 * The run's recorded intervals on one time axis, a row per task: queue waits, dependency gates, event and child-run
 * waits apart from execution. Every bar is a button whose description names its times and outcome; an open interval
 * runs to now and says so. Nothing is drawn from configuration or inferred from gaps between timestamps.
 */
export function RunTimeline({ run, compact = false, order }: { run: RunView; compact?: boolean; order?: string[] }) {
  const tz = useTimezone();
  const now = useNow();
  const [chosen, setChosen] = React.useState<string | null>(null);
  const timeline = run.timeline ?? [];
  const segments = compact ? compactSegments(timeline) : timeline;
  if (segments.length === 0) return <p className="m-0 text-sm text-muted">No queue, wait or execution has been recorded for this run.</p>;
  const live = run.status === "IN-PROGRESS";
  const runEnd = run.end_date ? Date.parse(run.end_date) : now;
  const endOf = (s: TimelineSegment) => (s.ended_at ? Date.parse(s.ended_at) : live ? now : runEnd);
  const start = Math.min(...segments.map((s) => Date.parse(s.started_at)));
  const span = Math.max(1, Math.max(...segments.map(endOf)) - start);
  const names = new Set(segments.map((s) => s.task_code ?? PIPELINE_ROW));
  const rows = order ? [...order.filter(name => names.delete(name)), ...names] : [...names];
  const keyOf = (s: TimelineSegment) => `${s.task_code ?? ""}:${s.kind}:${s.attempt_number ?? ""}:${s.started_at}`;
  const picked = segments.find((s) => keyOf(s) === chosen);
  const kinds = [...new Set(segments.map((s) => s.kind))];
  return (
    <section aria-label="Timeline" className="grid gap-3">
      <ul aria-label="Timeline key" className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-muted">
        {kinds.map((kind) => (
          <li key={kind} className="flex items-center gap-1.5">
            <span aria-hidden className={cn("inline-block h-3 w-5 rounded-sm", KIND[kind].className)} />
            {KIND[kind].label}
          </li>
        ))}
      </ul>
      <div className={compact ? "min-w-0" : "overflow-x-auto"} data-scroll-area={compact ? undefined : true}>
        <div className={cn("grid gap-1", !compact && "min-w-[36rem]")} role="list" aria-label="Tasks on the run's time axis">
          {rows.map((row) => (
            <div key={row} role="listitem" className="grid grid-cols-[9rem_1fr] items-center gap-2">
              <span className="sticky left-0 z-10 truncate bg-surface py-1 pr-1 text-xs font-medium" title={row}>{row}</span>
              <div className="relative h-control rounded-sm bg-surface-2">
                {segments
                  .filter((s) => (s.task_code ?? PIPELINE_ROW) === row)
                  .map((s) => {
                    const open = !s.ended_at && s.outcome !== "ENDED";
                    const left = ((Date.parse(s.started_at) - start) / span) * 100;
                    const width = Math.max(((endOf(s) - Date.parse(s.started_at)) / span) * 100, 0.6);
                    const { icon: Icon, spin } = statusMeta(s.outcome);
                    const execution = s.kind === "EXECUTION";
                    return (
                      <button
                        key={keyOf(s)}
                        type="button"
                        aria-label={describe(s, tz, open)}
                        aria-pressed={keyOf(s) === chosen}
                        title={describe(s, tz, open)}
                        onClick={() => setChosen(keyOf(s))}
                        onFocus={() => setChosen(keyOf(s))}
                        data-open={open || undefined}
                        className={cn(
                          "timeline-bar absolute flex items-center overflow-hidden rounded-sm px-0.5 outline-offset-1",
                          execution ? cn("top-1 bottom-1", statusSolid(s.outcome)) : cn("top-0.5 bottom-0.5 text-fg", KIND[s.kind].className, compact && "opacity-40"),
                        )}
                        style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }}
                      >
                        {!compact ? <Icon aria-hidden className={cn("size-3 shrink-0", spin && open && "animate-spin")} /> : null}
                      </button>
                    );
                  })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <p aria-live="polite" className="m-0 min-h-5 text-xs text-muted">
        {picked ? describe(picked, tz, !picked.ended_at && picked.outcome !== "ENDED") : "Select a bar, or tab to it, to read its times and outcome."}
      </p>
    </section>
  );
}
