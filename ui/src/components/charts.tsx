import * as React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatSeconds, measured } from "@/lib/format";
import type { DayInsight } from "@/lib/types";
import { EmptyState } from "@/components/common";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

/** A headline number with a line of context: the form for one value, not a chart. */
export function KpiTile({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "bad" | "warn" | "ok" }) {
  return (
    <div data-card className="grid min-w-0 gap-0.5 rounded-sm border border-border bg-surface px-5 py-4">
      <span className="truncate text-xs text-muted">{label}</span>
      <span className={cn("truncate text-[28px] font-semibold leading-9 tracking-tight", tone === "bad" && "text-bad", tone === "warn" && "text-warn", tone === "ok" && "text-ok")}>{value}</span>
      <span className="truncate text-xs text-muted">{hint ?? " "}</span>
    </div>
  );
}

/** A titled panel whose body fills the rest of its height. */
export function Panel({ title, aside, className, children }: { title: string; aside?: React.ReactNode; className?: string; children: React.ReactNode }) {
  return (
    <section data-card aria-label={title} className={cn("flex min-h-0 min-w-0 flex-col rounded-lg border border-border bg-surface", className)}>
      <header className="flex shrink-0 items-center justify-between gap-2 px-5 pb-1 pt-4">
        <h2 className="m-0 truncate text-sm font-semibold">{title}</h2>
        {aside}
      </header>
      <div className="flex min-h-0 flex-1 flex-col px-5 pb-4 pt-2">{children}</div>
    </section>
  );
}

export interface BarRow {
  label: string;
  value: number;
  text?: string;
  to?: string;
  tone?: "ok" | "bad" | "accent" | "warn";
}

const FILL = { ok: "bg-ok-solid", bad: "bg-bad-solid", accent: "bg-accent", warn: "bg-warn-solid" } as const;

/** Ranked horizontal bars: names on the left where they can be read, the value at the end of each bar. */
export function HBars({ rows, empty, nextStep, label }: { rows: BarRow[]; empty: string; nextStep: React.ReactNode; label: string }) {
  const top = Math.max(1e-9, ...rows.map((r) => r.value));
  if (rows.length === 0) return <EmptyState title={empty} nextStep={nextStep} />;
  if (rows.length < 5) return <dl aria-label={label} className="m-0 grid content-start gap-2 text-[13px]">{rows.map((row) => <div key={row.label} className="flex justify-between gap-4"><dt>{row.to ? <Link className="hover:underline" to={row.to}>{row.label}</Link> : row.label}</dt><dd className="num m-0">{row.text ?? row.value}</dd></div>)}</dl>;
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

const dayLabel = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function Readout({ active, payload, label }: { active?: boolean; payload?: { payload: DayInsight }[]; label?: string }) {
  const day = payload?.[0]?.payload;
  if (!active || !day) return null;
  return (
    <div className="grid gap-1 rounded-lg bg-surface px-3 py-2 text-xs shadow-pop">
      <span className="font-medium">{dayLabel(label ?? day.day)}</span>
      <span className="flex items-center gap-2"><i aria-hidden className="size-2 rounded-full bg-ok-solid" />{day.succeeded} succeeded</span>
      <span className="flex items-center gap-2"><i aria-hidden className="size-2 rounded-full bg-bad-solid" />{day.failed} failed</span>
      {day.runs - day.succeeded - day.failed > 0 ? <span className="flex items-center gap-2"><i aria-hidden className="size-2 rounded-full bg-idle-solid" />{day.runs - day.succeeded - day.failed} other</span> : null}
    </div>
  );
}

/** Short daily windows are dated numbers; larger windows retain a slot for every day. */
export function DailyRuns({ days }: { days: DayInsight[] }) {
  if (days.length < 5) return (
    <dl aria-label="Daily run totals" className="m-0 grid content-start gap-3 px-5 pb-5 pt-4 text-[13px]">
      {days.map((day) => (
        <div key={day.day} className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-t border-border pt-2">
          <dt className="font-medium"><time dateTime={day.day}>{dayLabel(day.day)}</time></dt>
          <dd className="num m-0 grid gap-0.5 text-right">
            <span>{measured(day.runs)} {day.runs === 1 ? "run" : "runs"} · {measured(day.succeeded)} succeeded · {measured(day.failed)} failed{day.runs > day.succeeded + day.failed ? ` · ${measured(day.runs - day.succeeded - day.failed)} other` : ""}</span>
            <span className="text-xs text-muted">{day.average_seconds === null ? "No finished runs" : `Average duration ${formatSeconds(day.average_seconds)}`}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
  const rows = days.map((day) => ({ ...day, other: day.runs - day.succeeded - day.failed }));
  return (
      <div className="h-64 px-3 pb-3 pt-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -18 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 4" />
            <XAxis dataKey="day" tickFormatter={dayLabel} tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 11 }} tickMargin={8} minTickGap={16} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 11 }} width={44} />
            <Tooltip cursor={{ fill: "var(--surface-2)" }} content={<Readout />} />
            <Bar dataKey="succeeded" stackId="runs" fill="var(--ok-solid)" maxBarSize={36} radius={[0, 0, 3, 3]} />
            <Bar dataKey="failed" stackId="runs" fill="var(--bad-solid)" maxBarSize={36} />
            <Bar dataKey="other" stackId="runs" fill="var(--idle-solid)" maxBarSize={36} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
  );
}
