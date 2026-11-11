import * as React from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DayInsight } from "@/lib/types";

import { dayLabel } from "@/lib/format";

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

export function DailyChart({ days }: { days: DayInsight[] }) {
  const rows = days.map((day) => ({ ...day, other: day.runs - day.succeeded - day.failed }));
  return (
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
  );
}

export function SparkChart({ data, color }: { data: { v: number | null }[]; color: string }) {
  const id = React.useId();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.75} fill={`url(#${id})`} connectNulls isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
