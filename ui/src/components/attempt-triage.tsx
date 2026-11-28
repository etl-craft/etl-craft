import { useActionReason } from "@/components/action-reason";
import { Table, Td, Th } from "@/components/ui/table";
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

export function MedianMark({ value, sample, format, showSample = true, onValue }: { value: number; sample?: MetricMedian; format: (value: number) => string; showSample?: boolean; onValue?: () => void }) {
  const median = sample?.median;
  const mark = median != null && median > 0 ? value > 3 * median ? "▲" : value < median / 3 ? "▼" : null : null;
  const tooltip = useActionReason(mark && median ? `${new Intl.NumberFormat("en-GB", { maximumSignificantDigits: 3 }).format(value / median)}× median` : undefined);
  return <span className={showSample ? "inline-flex flex-wrap items-baseline gap-x-1 tabular-nums" : "inline-flex items-baseline justify-end gap-x-1 tabular-nums"}>
    {onValue ? <button type="button" className="text-accent hover:underline" aria-label={`Reject breakdown for ${format(value)} rows`} onClick={onValue}>{format(value)}</button> : <span>{format(value)}</span>}
    {mark ? <button type="button" className="hit-target relative text-warn" {...tooltip.anchor} onClick={tooltip.show} aria-label={mark === "▲" ? "Above three times the median" : "Below one third of the median"}>{mark}</button> : null}
    {sample && showSample ? <small className="whitespace-nowrap text-muted">med {median == null ? "—" : format(median)}, n={sample.sample_size}</small> : null}
    {tooltip.annotation}
  </span>;
}

const counts = [
  ["source_count", "Read"], ["rows_written", "Written"], ["reject_count", "Rejected"],
  ["insert_count", "Inserted"], ["update_count", "Updated"], ["delete_count", "Deleted"],
  ["duplicate_count", "Duplicates"], ["target_count", "Target rows"],
] as const;

export function AttemptStatistics({ attempt, metrics, now, onTimings, onRejects }: {
  attempt: AttemptView; metrics?: Record<string, MetricMedian>; now: number; onTimings?: () => void; onRejects?: () => void;
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
    <Table unwrapped aria-label="Attempt statistics" className="stacked-table evidence-table table-fixed tabular-nums">
      <colgroup><col className="w-[33%]" /><col className="w-[26%]" /><col className="w-[23%]" /><col /></colgroup>
      <thead><tr>
        <Th scope="col">Metric</Th><Th scope="col" className="text-right">This try</Th>
        <Th scope="col" className="text-right">Median</Th><Th scope="col" className="whitespace-nowrap text-right">Samples</Th>
      </tr></thead>
      <tbody>{facts.map(({ key, label, value, format }) => {
        if (value == null) return null;
        const sample = metrics?.[key];
        return <tr key={key}>
          <th scope="row" className="text-left font-medium">{label}</th>
          <Td data-label="This try" className="text-right"><MedianMark value={value} sample={sample} format={format} showSample={false} onValue={key === "reject_count" && value > 0 ? onRejects : undefined} /></Td>
          <Td data-label="Median" className="text-right">{sample?.median == null ? "—" : format(sample.median)}</Td>
          <Td data-label="Samples" className="text-right">{sample?.sample_size ?? "—"}</Td>
        </tr>;
      })}</tbody>
    </Table>
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
  const errors = [attempt.first_error, attempt.last_error];
  const fields = [
    { label: "Step", values: errors.map(error => error?.event.step) },
    { label: "Error class", values: errors.map(error => error?.event.error_class) },
    { label: "ExitCode", values: errors.map(error => error?.event.exit_code ?? attempt.exit_name) },
    { label: "Native code", values: errors.map(() => attempt.failure_code) },
    { label: "Failure class", values: errors.map(error => error?.event.failure_class) },
    { label: "Message", values: errors.map((error, index) => error?.text ?? (index === 0 ? attempt.error_message?.split("\n")[0] : null)) },
    { label: "Log", values: errors.map((error, index) => {
      if (!error) return `${index === 0 ? "First" : "Last"} error was not recorded for try ${attempt.attempt_number}.`;
      const line = error.state === "LIVE" || error.state === "ARCHIVED" ? error.line : null;
      return <>
        {error.state === "ARCHIVED" ? <span className="block">Archived log</span> : null}
        {error.message}
        {line != null && onLine ? <button type="button" className="text-left text-accent hover:underline" aria-label={`Go to line ${line} for ${index === 0 ? "first" : "last"} error`} onClick={() => onLine(line)}>Go to line {line}</button> : null}
      </>;
    }) },
  ];
  return <section aria-label="Failure summary" className="grid gap-2 rounded-md border border-bad bg-surface p-2">
    <strong className="text-sm text-bad">× Failure summary</strong>
    <Table unwrapped aria-label="First and last error" className="stacked-table evidence-table table-fixed">
      <colgroup><col className="w-1/4" /><col /><col /></colgroup>
      <thead><tr><Th scope="col">Field</Th><Th scope="col">First error</Th><Th scope="col">Last error</Th></tr></thead>
      <tbody>{fields.filter(({ values }) => values.some(value => value != null)).map(({ label, values }) => <tr key={label}>
        <th scope="row" className="text-left font-medium">{label}</th>
        <Td data-label="First error">{values[0] ?? "—"}</Td>
        <Td data-label="Last error">{values[1] ?? "—"}</Td>
      </tr>)}</tbody>
    </Table>
  </section>;
}
