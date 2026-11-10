import * as React from "react";
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
export function HBars({ rows, empty, label }: { rows: BarRow[]; empty: string; label: string }) {
  const top = Math.max(1e-9, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="m-0 text-sm text-muted">{empty}</p>;
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
