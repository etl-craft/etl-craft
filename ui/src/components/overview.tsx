import { EmptyState } from "@/components/common";
import { DailyRuns, Spark } from "@/components/charts";
import { RunLabel } from "@/components/run-label";
import { ArrowUpRight, Timer } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { StatusMark } from "@/components/status";
import { When } from "@/components/when";
import { formatDuration, formatSeconds, percent, seconds } from "@/lib/format";
import { pipelinePath, runPath, runsPath } from "@/lib/routes";
import type { DayInsight, Insights, PipelineInsight, RunView } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY = 86_400_000;

/** Every UTC day of the window, so a quiet day is a gap in the chart instead of a missing column. */
export function everyDay(days: DayInsight[], start: string, end: string): DayInsight[] {
  const have = new Map(days.map((d) => [d.day, d]));
  const first = Date.parse(start.slice(0, 10) + "T00:00:00Z");
  const last = Math.max(first, Date.parse(end) - 1);
  const out: DayInsight[] = [];
  for (let at = first; at <= last && out.length < 366; at += DAY) {
    const day = new Date(at).toISOString().slice(0, 10);
    out.push(have.get(day) ?? { day, runs: 0, succeeded: 0, failed: 0, average_seconds: null });
  }
  return out;
}

function Tile({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return <section className={cn("min-w-0 rounded-xl bg-surface shadow-raised", className)} {...props} />;
}

function TileTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <header className="flex items-center justify-between gap-3 px-5 pt-4">
      <h2 className="m-0 text-[13px] font-medium text-muted">{children}</h2>
      {aside}
    </header>
  );
}

/** What happened in the window, said in one sentence, above the runs of each day. */
function Headline({ d, days }: { d: Insights; days: DayInsight[] }) {
  const t = d.total;
  const sentence = !t.runs ? "No runs yet in this window" : t.failed ? `${t.failed} of ${t.runs} runs failed` : `All ${t.runs} runs succeeded`;
  return (
    <Tile aria-label="Runs per day" className="flex flex-col lg:col-span-2">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 px-5 pt-5">
        <div className="grid gap-1">
          <p className="m-0 text-[26px] font-semibold leading-8 tracking-tight">{sentence}</p>
          <p className="m-0 text-[13px] text-muted">
            {percent(t.success_rate)} success rate
            {t.in_progress ? `, ${t.in_progress} running now` : ""}
            {t.sla_breached ? `, ${t.sla_breached} past their SLA` : ""}
          </p>
        </div>
        <p className="m-0 flex items-center gap-4 text-xs text-muted">
          <span className="flex items-center gap-1.5"><i aria-hidden className="size-2 rounded-full bg-ok-solid" />Succeeded</span>
          <span className="flex items-center gap-1.5"><i aria-hidden className="size-2 rounded-full bg-bad-solid" />Failed</span>
          <span className="flex items-center gap-1.5"><i aria-hidden className="size-2 rounded-full bg-idle-solid" />Other</span>
        </p>
      </div>
      <DailyRuns days={days} />
    </Tile>
  );
}

/** The runs someone should look at first: failures, then a count of SLA misses. */
function Attention({ code, d }: { code: string; d: Insights }) {
  const failed = d.latest.filter((r) => r.status === "FAILED").slice(0, 5);
  const quiet = !failed.length && !d.total.sla_breached;
  return (
    <Tile aria-label="Needs attention" className="flex flex-col">
      <TileTitle>Needs attention</TileTitle>
      {quiet ? (
        <EmptyState title="Nothing failed in this window" nextStep="Choose a wider time range to inspect earlier failures, or open Runs for all outcomes." />
      ) : (
        <ul className="m-0 grid list-none content-start gap-0.5 p-2">
          {failed.map((r) => (
            <li key={r.pipeline_run_id}>
              <Link to={runPath(code, r.pipeline_code, r.pipeline_run_id)} className="group flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-surface-2">
                <StatusMark status={r.status} solid className="rounded-full" />
                <span className="grid min-w-0 flex-1">
                  <span className="truncate text-[13px] font-medium">{r.pipeline_code} <RunLabel id={r.pipeline_run_id} label={r.run_label} /></span>
                  <span className="text-xs text-muted">Failed <When iso={r.end_date ?? r.start_date} /></span>
                </span>
                <ArrowUpRight aria-hidden className="size-4 text-muted opacity-0 group-hover:opacity-100" />
              </Link>
            </li>
          ))}
          {d.total.sla_breached ? (
            <li className="flex items-center gap-3 px-3 py-2">
              <span className="grid size-5 place-items-center rounded-full bg-warn-solid text-white"><Timer aria-hidden className="size-3" strokeWidth={2.5} /></span>
              <span className="text-[13px]">{d.total.sla_breached} run{d.total.sla_breached === 1 ? "" : "s"} past the SLA</span>
            </li>
          ) : null}
        </ul>
      )}
    </Tile>
  );
}

function Figure({ label, value, format, suffix, show, text, hint, spark }: { label: string; value: number | null; format?: Intl.NumberFormatOptions; suffix?: string; show?: (value: number) => string; text?: string; hint?: string; spark?: React.ReactNode }) {
  return (
    <Tile aria-label={label} className="grid content-between gap-2">
      <div className="grid gap-1 px-5 pb-3 pt-4">
        <span className="text-[13px] font-medium text-muted">{label}</span>
        <span className="num text-[28px] font-semibold leading-9 tracking-tight">
          {value === null ? <span className="text-base font-normal text-muted">{text ?? "Not measured"}</span> : show ? show(value) : <>{value.toLocaleString("en-GB", format)}{suffix}</>}
        </span>
        <span className="text-xs text-muted">{hint ?? " "}</span>
      </div>
      {spark ?? null}
    </Tile>
  );
}

function PipelineRow({ code, p }: { code: string; p: PipelineInsight }) {
  const other = Math.max(0, p.runs - p.succeeded - p.failed);
  const share = (n: number) => `${(n / Math.max(1, p.runs)) * 100}%`;
  return (
    <li>
      <Link to={pipelinePath(code, p.pipeline_code ?? "")} className="grid grid-cols-[minmax(0,1fr)_minmax(4rem,9rem)_3rem_4.5rem] items-center gap-4 rounded-lg px-3 py-2 hover:bg-surface-2">
        <span className="truncate text-[13px] font-medium">{p.pipeline_code}</span>
        <span role="img" aria-label={`${p.succeeded} succeeded, ${p.failed} failed of ${p.runs}`} className="flex h-1.5 gap-0.5 overflow-hidden rounded-full">
          {p.succeeded ? <i className="rounded-full bg-ok-solid" style={{ width: share(p.succeeded) }} /> : null}
          {p.failed ? <i className="rounded-full bg-bad-solid" style={{ width: share(p.failed) }} /> : null}
          {other ? <i className="rounded-full bg-idle-solid" style={{ width: share(other) }} /> : null}
        </span>
        <span className={cn("num text-right text-[13px]", p.failed ? "text-bad" : "text-fg")}>{p.success_rate === null ? "—" : percent(p.success_rate)}</span>
        <span className="num text-right text-xs text-muted">{p.average_seconds === null ? "—" : seconds(p.average_seconds)}</span>
      </Link>
    </li>
  );
}

function RunRow({ code, r }: { code: string; r: RunView }) {
  return (
    <li>
      <Link to={runPath(code, r.pipeline_code, r.pipeline_run_id)} className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-surface-2">
        <StatusMark status={r.status} solid className="rounded-full" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{r.pipeline_code} <RunLabel id={r.pipeline_run_id} label={r.run_label} /></span>
        <span className="num text-xs text-muted">{r.end_date ? formatDuration(r.start_date, r.end_date) : ""}</span>
        <span className="text-right text-xs text-muted"><When iso={r.start_date} /></span>
      </Link>
    </li>
  );
}

/** The project at a glance: what happened, what needs a look, the headline numbers, then pipelines and the newest runs. */
export function Overview({ code, d }: { code: string; d: Insights }) {
  const t = d.total;
  const days = everyDay(d.days, d.window_start, d.window_end);
  const worst = [...d.per_pipeline].sort((a, b) => (a.success_rate ?? 2) - (b.success_rate ?? 2));
  return (
    <div className="grid content-start gap-4 bg-bg p-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Headline d={d} days={days} />
        <Attention code={code} d={d} />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Figure label="Runs" value={t.runs} hint={t.in_progress ? `${t.in_progress} running now` : `${t.finished} finished`} spark={<Spark color="var(--accent)" data={days.map((x) => ({ v: x.runs }))} />} />
        <Figure label="Average duration" value={t.average_seconds} show={formatSeconds} text="No finished runs" hint={t.longest_seconds === null ? undefined : `longest ${seconds(t.longest_seconds)}`} spark={<Spark color="var(--run-solid)" data={days.map((x) => ({ v: x.average_seconds }))} />} />
        <Figure label="Retries" value={t.retries} hint={t.lost_attempts ? `${t.lost_attempts} attempts lost` : `${t.attempts} attempts`} />
        {t.rows_written !== null ? <Figure label="Rows written" value={t.rows_written} format={{ notation: "compact", maximumFractionDigits: 1 }} hint={t.rows_per_second === null ? undefined : `${t.rows_per_second.toFixed(1)} rows/s`} /> : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Tile aria-label="Success rate by pipeline">
          <TileTitle aside={<span className="text-xs text-muted">success · average</span>}>Pipelines, least healthy first</TileTitle>
          {worst.length ? <ul className="m-0 grid list-none gap-0.5 p-2">{worst.slice(0, 8).map((p) => <PipelineRow key={p.pipeline_code} code={code} p={p} />)}</ul> : <EmptyState title="No pipeline ran in this window." nextStep="Choose a wider time range or run a pipeline from Pipelines." />}
        </Tile>
        <Tile aria-label="Latest runs">
          <TileTitle aside={<Link className="text-xs font-medium text-fg hover:text-accent hover:underline" to={runsPath(code)}>All runs</Link>}>Latest runs</TileTitle>
          {d.latest.length ? <ul className="m-0 grid list-none gap-0.5 p-2">{d.latest.slice(0, 8).map((r) => <RunRow key={r.pipeline_run_id} code={code} r={r} />)}</ul> : <EmptyState title="No runs in this window." nextStep="Choose a wider time range or run a pipeline from Pipelines." />}
        </Tile>
      </div>
    </div>
  );
}
