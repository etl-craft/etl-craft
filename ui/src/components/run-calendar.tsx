import * as React from "react";
import { EmptyState } from "@/components/common";
import { isFailure, toneClass } from "@/components/status";
import type { RunView } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY = 86_400_000;
const WEEKS = 12;
const day = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/** Runs by day over twelve weeks, each day coloured by its worst run: a gap in a column shows where nothing ran. */
export function RunCalendar({ runs }: { runs: RunView[] }) {
  const [today] = React.useState(() => Date.now());
  const byDay = new Map<string, RunView[]>();
  for (const run of runs) if (run.start_date) byDay.set(run.start_date.slice(0, 10), [...(byDay.get(run.start_date.slice(0, 10)) ?? []), run]);
  // Until runs cover five days, twelve weeks of empty squares hide them: the days are listed instead.
  if (byDay.size < 5)
    return (
      <div className="grid gap-2">
        {byDay.size ? <p className="m-0 text-[13px] text-muted">Runs on {byDay.size} day{byDay.size === 1 ? "" : "s"} so far; the calendar appears once runs cover five days.</p> : <EmptyState title="No runs yet." nextStep="Use Run now on this pipeline to record its first run." />}
        <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
          {[...byDay.entries()].sort(([x], [y]) => y.localeCompare(x)).map(([key, list]) => {
            const failed = list.filter((r) => isFailure(r.status)).length;
            return (
              <li key={key} className="flex items-center gap-3">
                <span className="num w-24">{key}</span>
                <span className="num">{list.length} run{list.length === 1 ? "" : "s"}</span>
                {failed ? <span className="num font-medium text-bad">{failed} failed</span> : null}
              </li>
            );
          })}
        </ul>
      </div>
    );
  const last = new Date(today);
  const monday = today - ((last.getUTCDay() + 6) % 7) * DAY - (WEEKS - 1) * 7 * DAY;
  const weeks = Array.from({ length: WEEKS }, (_, w) => Array.from({ length: 7 }, (_, d) => monday + (w * 7 + d) * DAY));
  // A day takes its worst run's colour: failed, then running, then green only when every run succeeded.
  const worst = (list: RunView[]) =>
    list.some((r) => isFailure(r.status)) ? "FAILED" : list.some((r) => r.status === "IN-PROGRESS") ? "IN-PROGRESS" : list.every((r) => r.status === "SUCCESS") ? "SUCCESS" : "SKIPPED";
  const names = ["Mon", "", "Wed", "", "Fri", "", ""];
  return (
    <div className="grid gap-2">
      <div className="flex gap-1 overflow-x-auto pb-1" role="grid" aria-label="Runs by day">
        <div className="grid gap-1 pt-5 pr-1 text-[10px] leading-5 text-muted" aria-hidden>
          {names.map((n, i) => (
            <span key={i} className="h-5">
              {n}
            </span>
          ))}
        </div>
        {weeks.map((week, w) => {
          const month = new Date(week[0]!).toLocaleString("en", { month: "short", timeZone: "UTC" });
          const previous = w > 0 ? new Date(weeks[w - 1]![0]!).toLocaleString("en", { month: "short", timeZone: "UTC" }) : "";
          return (
            <div key={week[0]} className="grid gap-1" role="row">
              <span className="h-4 text-[10px] leading-4 text-muted" aria-hidden>
                {month !== previous ? month : ""}
              </span>
              {week.map((ms) => {
                const key = day(ms);
                const list = byDay.get(key) ?? [];
                const label = `${key}: ${list.length ? `${list.length} run${list.length === 1 ? "" : "s"}, ${list.filter((r) => isFailure(r.status)).length} failed` : "no runs"}`;
                return <span key={key} role="gridcell" aria-label={label} title={label} className={cn("size-5 rounded-sm border", ms > today ? "border-transparent" : list.length ? cn(toneClass(worst(list)), "border-current") : "border-border bg-surface-2")} />;
              })}
            </div>
          );
        })}
      </div>
      <p className="m-0 text-xs text-muted">Each square is a day, oldest week on the left. A red square had a failed run; hover a square for its counts.</p>
    </div>
  );
}
