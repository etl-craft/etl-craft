import { useActionReason } from "@/components/action-reason";
import { Fact, FactList } from "@/components/common";
import { isFailure } from "@/components/status";
import { formatSeconds } from "@/lib/format";
import type { AttemptView, MetricMedian } from "@/lib/types";

const number = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
export function compactCount(value: number): string {
  if (value >= 999_950) return `${number.format(value / 1_000_000)}M`;
  if (value >= 1_000) return `${number.format(value / 1_000)}k`;
  return number.format(value);
}
export const memory = (bytes: number) => `${number.format(bytes / 1_048_576)} MiB`;
export const cores = (value: number) => `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 }).format(value)} cores`;
export const interval = (start?: string | null, end?: string | null) =>
  start && end ? Math.max(0, (Date.parse(end) - Date.parse(start)) / 1000) : null;
export const executionSeconds = (attempt: Pick<AttemptView, "started_at" | "ended_at" | "status">, now: string) =>
  interval(attempt.started_at, attempt.ended_at ?? (attempt.status === "RUNNING" ? now : null));
export const perSecond = (value: number | null | undefined, duration: number | null) =>
  value != null && duration != null && duration > 0 ? value / duration : null;

export function MedianMark({ value, sample, format }: { value: number; sample?: MetricMedian; format: (value: number) => string }) {
  const median = sample?.median;
  const mark = median != null && median > 0 ? value > 3 * median ? "▲" : value < median / 3 ? "▼" : null : null;
  const tooltip = useActionReason(mark && median ? `${new Intl.NumberFormat("en-GB", { maximumSignificantDigits: 3 }).format(value / median)}× median` : undefined);
  return <span className="inline-flex flex-wrap items-baseline gap-x-1 tabular-nums">
    <span>{format(value)}</span>
    {mark ? <button type="button" className="hit-target relative text-warn" {...tooltip.anchor} onClick={tooltip.show} aria-label={mark === "▲" ? "Above three times the median" : "Below one third of the median"}>{mark}</button> : null}
    {sample ? <small className="whitespace-nowrap text-muted">med {median == null ? "—" : format(median)}, n={sample.sample_size}</small> : null}
    {tooltip.annotation}
  </span>;
}

const counts = [
  ["source_count", "Read"], ["rows_written", "Written"], ["reject_count", "Rejected"],
  ["insert_count", "Inserted"], ["update_count", "Updated"], ["delete_count", "Deleted"],
  ["duplicate_count", "Duplicates"], ["target_count", "Target rows"],
] as const;

export function AttemptStatistics({ attempt, metrics, now, onTimings }: {
  attempt: AttemptView; metrics?: Record<string, MetricMedian>; now: number; onTimings?: () => void;
}) {
  const duration = executionSeconds(attempt, new Date(now).toISOString());
  const facts = [
    ...counts.map(([key, label]) => ({ key, label, value: attempt[key], format: compactCount })),
    { key: "queue_seconds", label: "Queue time", value: interval(attempt.queued_at, attempt.started_at), format: formatSeconds },
    { key: "duration_seconds", label: "Execution time", value: duration, format: formatSeconds },
    { key: "rows_per_second", label: "Rows a second", value: perSecond(attempt.source_count, duration), format: compactCount },
    { key: "peak_rss_bytes", label: "Peak memory", value: attempt.peak_rss_bytes, format: memory },
    { key: "average_cores", label: "CPU", value: perSecond(attempt.cpu_seconds, interval(attempt.started_at, attempt.ended_at)), format: cores },
  ].filter(({ value }) => value != null);
  if (!facts.length) return null;
  return <section aria-label="Attempt statistics" className="grid gap-2 rounded-md border border-border bg-surface-2 p-2">
    <FactList inline>
      {facts.map(({ key, label, value, format }) => value != null ? <Fact inline key={key} label={label}><MedianMark value={value} sample={metrics?.[key]} format={format} /></Fact> : null)}
    </FactList>
    {onTimings ? <button type="button" className="w-fit text-left text-xs text-accent hover:underline" onClick={onTimings}>Step timings in log</button> : null}
  </section>;
}

type FailureAttempt = Pick<AttemptView, "attempt_number" | "status" | "failure_code" | "first_error" | "last_error" | "error_message"> & { exit_name?: string | null };

export function FailureSummary({ attempt, onLine, compact = false }: {
  attempt: FailureAttempt; onLine?: (line: number) => void; compact?: boolean;
}) {
  if (!isFailure(attempt.status)) return null;
  const code = attempt.last_error?.event.exit_code ?? attempt.first_error?.event.exit_code ?? attempt.exit_name;
  const codes = <>{code ? <span>ExitCode {code}</span> : null}{attempt.failure_code ? <span>Native code {attempt.failure_code}</span> : null}</>;
  if (compact) return codes;
  return <section aria-label="Failure summary" className="grid gap-2 rounded-md border border-bad bg-surface p-2 text-sm">
    <div className="flex flex-wrap gap-x-2 break-words"><strong className="text-bad">× Failure summary</strong>{codes}</div>
    {([["First error", attempt.first_error], ["Last error", attempt.last_error]] as const).map(([label, error]) => {
      const line = error && (error.state === "LIVE" || error.state === "ARCHIVED") ? error.line : null;
      return <div key={label} className="grid min-w-0 gap-0.5 break-words">
        <span className="font-medium">{label}</span>
        {error ? <>
          <span>{[error.event.step, error.event.error_class, error.event.exit_code, error.event.failure_class].filter(Boolean).join(" · ")}</span>
          {error.text ? <span className="text-muted">{error.text}</span> : null}
          {error.state === "ARCHIVED" ? <span>Archived log</span> : null}
          {error.message ? <span>{error.message}</span> : null}
          {line != null && onLine ? <button type="button" className="w-fit text-accent hover:underline" aria-label={`Go to line ${line} for ${label.toLowerCase()}`} onClick={() => onLine(line)}>Go to line {line}</button> : null}
        </> : <span>{label} was not recorded for try {attempt.attempt_number}.</span>}
      </div>;
    })}
    {!attempt.first_error && attempt.error_message ? <span>{attempt.error_message.split("\n")[0]}</span> : null}
  </section>;
}
