import * as React from "react";
import { Link } from "react-router-dom";
import type { DayInsight } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A headline number with a line of context: the form for one value, not a chart. */
export function KpiTile({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "bad" | "warn" | "ok" }) {
  return (
    <div className="grid min-w-0 gap-0.5 rounded-lg border border-border bg-surface px-3 py-2.5">
      <span className="truncate text-xs text-muted">{label}</span>
      <span className={cn("truncate text-2xl font-semibold leading-tight", tone === "bad" && "text-bad", tone === "warn" && "text-warn", tone === "ok" && "text-ok")}>{value}</span>
      <span className="truncate text-xs text-muted">{hint ?? " "}</span>
    </div>
  );
}

/** A titled panel whose body fills the rest of its height. */
export function Panel({ title, aside, className, children }: { title: string; aside?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className={cn("flex min-h-0 min-w-0 flex-col rounded-lg border border-border bg-surface", className)}>
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2">
        <h2 className="m-0 truncate text-sm font-semibold">{title}</h2>
        {aside}
      </header>
      <div className="flex min-h-0 flex-1 flex-col p-3">{children}</div>
    </section>
  );
}

const tick = (max: number) => (max <= 4 ? max : Math.ceil(max / 4) * 4);

/** Runs per day, stacked: the readout above names the day under the pointer or focus; a table carries the same numbers elsewhere. */
export function StackedBars({ days }: { days: DayInsight[] }) {
  const [at, setAt] = React.useState<number | null>(null);
  const top = tick(Math.max(1, ...days.map((d) => d.runs)));
  const shown = at === null ? null : days[at];
  const every = Math.max(1, Math.ceil(days.length / 14));
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <p className="m-0 flex h-5 flex-wrap items-center gap-x-3 text-xs" role="status">
        {shown ? (
          <>
            <span className="font-medium">{shown.day}</span>
            <span>{shown.runs} runs</span>
            <span className="text-ok">{shown.succeeded} succeeded</span>
            <span className={shown.failed ? "text-bad" : "text-muted"}>{shown.failed} failed</span>
          </>
        ) : (
          <span className="flex items-center gap-3 text-muted">
            <span><span aria-hidden className="mr-1 inline-block size-2 rounded-sm bg-ok" />Succeeded</span>
            <span><span aria-hidden className="mr-1 inline-block size-2 rounded-sm bg-bad" />Failed</span>
            <span><span aria-hidden className="mr-1 inline-block size-2 rounded-sm bg-idle-bg ring-1 ring-border-strong" />Other</span>
          </span>
        )}
      </p>
      <div className="relative flex min-h-24 flex-1 gap-2">
        <div className="relative w-7 shrink-0 text-right text-[10px] text-muted" aria-hidden>
          {[1, 0.5, 0].map((f) => (
            <span key={f} className="absolute right-0 -translate-y-1/2" style={{ top: `${(1 - f) * 100}%` }}>
              {Math.round(top * f)}
            </span>
          ))}
        </div>
        <div className="relative min-w-0 flex-1">
          {[0, 0.5, 1].map((f) => (
            <span key={f} aria-hidden className="absolute inset-x-0 border-t border-border" style={{ top: `${f * 100}%` }} />
          ))}
          <ul className="absolute inset-0 m-0 flex list-none items-end gap-1 p-0" aria-label="Runs per day">
            {days.map((d, i) => {
              const other = d.runs - d.succeeded - d.failed;
              const pct = (n: number) => `${(n / top) * 100}%`;
              return (
                <li key={d.day} className="flex h-full min-w-1 max-w-14 flex-1 flex-col justify-end" onPointerEnter={() => setAt(i)} onPointerLeave={() => setAt(null)}>
                  <button type="button" className="flex h-full w-full flex-col justify-end outline-none focus-visible:ring-2 focus-visible:ring-accent" aria-label={`${d.day}: ${d.runs} runs, ${d.succeeded} succeeded, ${d.failed} failed`} onFocus={() => setAt(i)} onBlur={() => setAt(null)}>
                    <span aria-hidden className="block w-full bg-idle-bg" style={{ height: pct(other) }} />
                    <span aria-hidden className="block w-full border-t-2 border-surface bg-bad" style={{ height: pct(d.failed), borderTopWidth: d.failed ? 2 : 0 }} />
                    <span aria-hidden className={cn("block w-full rounded-t-sm bg-ok", at === i && "opacity-80")} style={{ height: pct(d.succeeded) }} />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
      <div className="flex gap-2" aria-hidden>
        <span className="w-7 shrink-0" />
        <div className="flex min-w-0 flex-1 gap-1 text-[10px] text-muted">
          {days.map((d, i) => (
            <span key={d.day} className="min-w-1 flex-1 overflow-visible whitespace-nowrap text-center">
              {i % every === 0 ? d.day.slice(5) : ""}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** One measure over days as a line: for a trend, where bars would suggest totals. */
export function Trend({ days, value, format }: { days: DayInsight[]; value: (d: DayInsight) => number | null; format: (n: number) => string }) {
  const [at, setAt] = React.useState<number | null>(null);
  const points = days.map((d) => value(d));
  const known = points.filter((p): p is number => p !== null);
  if (known.length === 0) return <p className="m-0 text-sm text-muted">No finished runs in this window.</p>;
  const top = Math.max(...known) || 1;
  const x = (i: number) => ((i + 0.5) / days.length) * 100;
  const y = (n: number) => 100 - (n / top) * 88 - 6;
  const line = points.flatMap((p, i) => (p === null ? [] : [`${x(i).toFixed(2)},${y(p).toFixed(2)}`]));
  const shown = at === null ? null : days[at];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <p className="m-0 h-5 text-xs" role="status">
        {shown ? (
          <>
            <span className="font-medium">{shown.day}</span> <span className="ml-2">{points[at!] === null ? "no finished runs" : format(points[at!]!)}</span>
          </>
        ) : (
          <span className="text-muted">Highest {format(top)}</span>
        )}
      </p>
      <div className="relative min-h-20 flex-1" onPointerLeave={() => setAt(null)}>
        {[0, 0.5, 1].map((f) => (
          <span key={f} aria-hidden className="absolute inset-x-0 border-t border-border" style={{ top: `${f * 100}%` }} />
        ))}
        <svg aria-hidden viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible">
          <polyline points={line.join(" ")} fill="none" stroke="var(--accent)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        </svg>
        {points.map((p, i) =>
          p === null ? null : <span key={days[i]!.day} aria-hidden className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-accent" style={{ left: `${x(i)}%`, top: `${y(p)}%` }} />,
        )}
        <ul className="absolute inset-0 m-0 flex list-none p-0">
          {days.map((d, i) => (
            <li key={d.day} className="h-full flex-1">
              <button type="button" className="size-full outline-none focus-visible:bg-accent/10" aria-label={`${d.day}: ${points[i] === null ? "no finished runs" : format(points[i]!)}`} onPointerEnter={() => setAt(i)} onFocus={() => setAt(i)} onBlur={() => setAt(null)} />
            </li>
          ))}
        </ul>
      </div>
      <div className="flex justify-between text-[10px] text-muted" aria-hidden>
        <span>{days[0]?.day.slice(5)}</span>
        <span>{days[days.length - 1]?.day.slice(5)}</span>
      </div>
    </div>
  );
}

export interface BarRow {
  label: string;
  value: number;
  text?: string;
  to?: string;
  tone?: "ok" | "bad" | "accent" | "warn";
}

const FILL = { ok: "bg-ok", bad: "bg-bad", accent: "bg-accent", warn: "bg-warn" } as const;

/** Ranked horizontal bars: names on the left where they can be read, the value at the end of each bar. */
export function HBars({ rows, empty, label }: { rows: BarRow[]; empty: string; label: string }) {
  const top = Math.max(1e-9, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="m-0 text-sm text-muted">{empty}</p>;
  return (
    <ul aria-label={label} className="m-0 grid min-h-0 flex-1 list-none content-start gap-1.5 overflow-auto p-0">
      {rows.map((r) => {
        const name = r.to ? (
          <Link to={r.to} className="truncate text-accent hover:underline" title={r.label}>
            {r.label}
          </Link>
        ) : (
          <span className="truncate" title={r.label}>
            {r.label}
          </span>
        );
        return (
          <li key={r.label} className="grid grid-cols-[minmax(6rem,11rem)_1fr_auto] items-center gap-2 text-[13px]">
            {name}
            <span className="h-2.5 rounded-sm bg-surface-2">
              <span className={cn("block h-full rounded-sm", FILL[r.tone ?? "accent"])} style={{ width: r.value > 0 ? `${Math.max(2, (r.value / top) * 100)}%` : 0 }} />
            </span>
            <span className="num w-14 text-right text-xs text-muted">{r.text ?? String(r.value)}</span>
          </li>
        );
      })}
    </ul>
  );
}
