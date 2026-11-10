import type { DayInsight } from "@/lib/types";

/** Runs per day, stacked: succeeded, failed, and the rest. The table beside it carries the same numbers. */
export function DayBars({ days }: { days: DayInsight[] }) {
  const tallest = Math.max(1, ...days.map((d) => d.runs));
  return (
    <ul className="m-0 flex h-36 list-none items-end justify-start gap-1.5 p-0" aria-label="Runs per day">
      {days.map((d) => {
        const other = d.runs - d.succeeded - d.failed;
        const pct = (n: number) => `${(n / tallest) * 100}%`;
        return (
          <li key={d.day} className="flex h-full w-full min-w-3 max-w-10 flex-col justify-end" title={`${d.day}: ${d.runs} runs, ${d.succeeded} succeeded, ${d.failed} failed`}>
            <span className="sr-only">{`${d.day}: ${d.runs} runs, ${d.succeeded} succeeded, ${d.failed} failed`}</span>
            <span aria-hidden className="block w-full bg-idle-bg" style={{ height: pct(other) }} />
            <span aria-hidden className="block w-full bg-bad-solid" style={{ height: pct(d.failed) }} />
            <span aria-hidden className="block w-full rounded-t-sm bg-ok-solid" style={{ height: pct(d.succeeded) }} />
            <span aria-hidden className="mt-1 text-center text-[10px] text-muted">
              {d.day.slice(8)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
