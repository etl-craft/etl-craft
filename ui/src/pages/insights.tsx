import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, Navigate, useLocation, useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { CsvButton } from "@/components/csv-button";
import { Field, inputClass, Loading, Notice, PageHeader } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { HBars, KpiTile, Panel, StackedBars, Trend, type BarRow } from "@/components/charts";
import { Tabs } from "@/components/tabs";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useProjectInfo, useRoleAtLeast, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatTime, measured, percent, seconds } from "@/lib/format";
import { catalogPath, pipelinePath, runPath } from "@/lib/routes";
import type { AgentsView, FailureInsight, Insights as InsightsView, Pipeline, PipelineInsight, RuleInsight, RunView, TaskInsight } from "@/lib/types";
import { projectHomePath } from "@/lib/routes";
import { useDocumentTitle } from "@/title";

const pipelineCol = createColumnHelper<PipelineInsight>();
const taskCol = createColumnHelper<TaskInsight>();
const failureCol = createColumnHelper<FailureInsight>();
const ruleCol = createColumnHelper<RuleInsight>();
const runCol = createColumnHelper<RunView>();
const num = (v: number | null) => <span className="num">{measured(v)}</span>;

/** The old address of this page: Home is the project's insights, so it opens Home with its filters. */
export function InsightsRedirect() {
  const { project = "" } = useParams();
  const { search } = useLocation();
  return <Navigate to={projectHomePath(project) + search} replace />;
}

/** Worker capacity: how much of each pool's advertised CPU and memory is in use, and how many attempts are running. */
function Capacity() {
  const list = useQuery({ queryKey: ["agents"], queryFn: () => getJson<AgentsView>("/api/v1/agents"), refetchInterval: 10_000 });
  if (list.isPending) return <Loading what="capacity" className="p-3" />;
  if (list.isError) return <Notice className="m-3">{(list.error as Error).message}</Notice>;
  const { agents, pools } = list.data;
  const live = agents.filter((a) => a.status === "ACTIVE");
  const running = agents.reduce((n, a) => n + a.attempts.length, 0);
  const used = (advertised: number, free: number) => (advertised > 0 ? Math.round(((advertised - free) / advertised) * 100) : 0);
  const cpu = pools.map((p) => ({ label: p.pool, value: used(p.advertised_cpu, p.free_cpu), text: `${used(p.advertised_cpu, p.free_cpu)}%`, tone: used(p.advertised_cpu, p.free_cpu) > 85 ? ("warn" as const) : ("accent" as const) }));
  const memory = pools.map((p) => ({ label: p.pool, value: used(p.advertised_memory_mb, p.free_memory_mb), text: `${used(p.advertised_memory_mb, p.free_memory_mb)}%`, tone: used(p.advertised_memory_mb, p.free_memory_mb) > 85 ? ("warn" as const) : ("accent" as const) }));
  return (
    <div className="flex min-h-0 flex-col">
      <div className="grid grid-cols-2 md:grid-cols-4">
        <KpiTile label="Active agents" value={live.length} hint={`${agents.length} registered`} />
        <KpiTile label="Draining" value={agents.filter((a) => a.status === "DRAINING").length} tone={agents.some((a) => a.status === "DRAINING") ? "warn" : undefined} />
        <KpiTile label="Running attempts" value={running} />
        <KpiTile label="Pools" value={pools.length} />
      </div>
      <div className="grid md:grid-cols-2">
        <Panel title="CPU in use by pool"><HBars label="CPU in use by pool" rows={cpu} empty="No pools yet." /></Panel>
        <Panel title="Memory in use by pool"><HBars label="Memory in use by pool" rows={memory} empty="No pools yet." /></Panel>
      </div>
    </div>
  );
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "pipelines", label: "Pipelines" },
  { id: "data", label: "Data" },
  { id: "quality", label: "Quality" },
  { id: "failures", label: "Failures" },
  { id: "runs", label: "Latest runs" },
  { id: "capacity", label: "Capacity" },
];

const RANGES: { id: string; label: string; days: number }[] = [
  { id: "1", label: "24 h", days: 1 },
  { id: "7", label: "7 days", days: 7 },
  { id: "30", label: "30 days", days: 30 },
];

const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/** A table's panel: it takes the room left in its pane and scrolls the rows inside. */
function TablePanel({ title, note, action, children }: { title: string; note?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="flex min-h-0 min-w-0 flex-1 flex-col">
      <CardHeader className="shrink-0">
        <div className="grid">
          <CardTitle>{title}</CardTitle>
          {note ? <span className="text-xs text-muted">{note}</span> : null}
        </div>
        {action}
      </CardHeader>
      <div data-scroll-area className="min-h-0 flex-1 overflow-auto">
        {children}
      </div>
    </Card>
  );
}

export function Insights() {
  const { project: code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tz = useTimezone();
  const developer = useRoleAtLeast("developer");
  const info = useProjectInfo(code);
  useDocumentTitle("Home", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const chosen = params.getAll("pipeline");
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const tab = TABS.some((t) => t.id === params.get("tab")) ? (params.get("tab") as string) : "overview";
  const choices = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`) });
  const found = useQuery({
    queryKey: ["insights", code, from, to, chosen],
    queryFn: () => getJson<InsightsView>(`${project(code)}/insights`, { start: from, end: to, pipelines: chosen }),
    refetchInterval: 30_000,
  });
  // Each change builds on the address as it is now, not as it was when the page last drew, so quick successive edits keep each other.
  const change = (edit: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(window.location.search);
    edit(next);
    setParams(next, { replace: true });
  };
  const set = (key: string, value: string | null) =>
    change((next) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
  const [today] = React.useState(() => Date.now());
  const preset = (days: number) =>
    change((next) => {
      next.set("from", isoDay(today - (days - 1) * 86_400_000));
      next.delete("to");
    });
  const activePreset = RANGES.find((r) => from === isoDay(today - (r.days - 1) * 86_400_000) && !to)?.id;
  const togglePipeline = (name: string) =>
    change((next) => {
      const now = next.getAll("pipeline");
      next.delete("pipeline");
      (now.includes(name) ? now.filter((c) => c !== name) : [...now, name]).forEach((c) => next.append("pipeline", c));
    });
  const d = found.data;
  const total = d?.total;
  const when = (value: string | null) => <span className="num whitespace-nowrap">{formatTime(value, tz)}</span>;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <PageHeader
        compact
        title="Home"
        subtitle={d ? `Runs started ${formatTime(d.window_start, tz)} to ${formatTime(d.window_end, tz)}; rates use finished runs.` : code}
        actions={
          <div className="flex flex-wrap items-end justify-end gap-2">
            <div role="group" aria-label="Time range" className="inline-flex rounded-md border border-border p-0.5 text-sm">
              {RANGES.map((r) => (
                <button key={r.id} type="button" aria-pressed={activePreset === r.id} onClick={() => preset(r.days)} className={cn("cursor-pointer rounded-sm px-2.5 py-1", activePreset === r.id ? "bg-accent/15 font-medium text-fg" : "text-muted hover:text-fg")}>
                  {r.label}
                </button>
              ))}
            </div>
            <Field compact label="From (UTC day)">
              <input type="date" value={from} onChange={(event) => set("from", event.target.value)} className={cn(inputClass, "w-36")} />
            </Field>
            <Field compact label="To (UTC day)">
              <input type="date" value={to} onChange={(event) => set("to", event.target.value)} className={cn(inputClass, "w-36")} />
            </Field>
            <details className="relative">
              <summary className="flex h-9 cursor-pointer items-center rounded-md border border-border-strong bg-surface px-3 text-sm max-sm:h-11">
                Pipelines {chosen.length ? `(${chosen.length} selected)` : "(all you can view)"}
              </summary>
              <fieldset className="absolute right-0 z-30 mt-1 grid max-h-72 min-w-64 gap-1 overflow-auto rounded-md border border-border bg-surface p-3 shadow-lg">
                <legend className="sr-only">Pipelines</legend>
                {(choices.data?.pipelines ?? []).map((p) => (
                  <label key={p.pipeline_code} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={chosen.includes(p.pipeline_code)} onChange={() => togglePipeline(p.pipeline_code)} /> {p.pipeline_code}
                  </label>
                ))}
              </fieldset>
            </details>
          </div>
        }
      />
      {found.isError ? <Notice>{(found.error as Error).message}</Notice> : null}
      {found.isPending ? <Loading what="the dashboard" /> : null}
      {d && total ? (
        <>
          <Tabs tabs={TABS} value={tab} onChange={(id) => set("tab", id === "overview" ? null : id)} />
          <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${tab}`} className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto lg:overflow-hidden">
            {tab === "capacity" ? <Capacity /> : null}
            {tab === "overview" ? <Overview code={code} d={d} when={when} /> : null}
            {tab === "pipelines" ? (
              <TablePanel
                title="Pipelines"
                action={
                  <CsvButton
                    size="sm"
                    name={`${code}-insights-pipelines.csv`}
                    header={["pipeline", "runs", "success_rate", "average_seconds", "longest_seconds", "sla_breached", "attempts", "retries", "lost", "rows_written", "rows_per_second"]}
                    rows={d.per_pipeline.map((p) => [p.pipeline_code, p.runs, p.success_rate, p.average_seconds, p.longest_seconds, p.sla_breached, p.attempts, p.retries, p.lost_attempts, p.rows_written, p.rows_per_second])}
                  />
                }
              >
                <DataTable
                  label="Pipelines"
                  data={d.per_pipeline}
                  empty="No pipeline ran in this window."
                  columns={[
                    pipelineCol.accessor("pipeline_code", { header: "Pipeline", cell: (c) => <Link className="font-medium text-accent hover:underline" to={pipelinePath(code, c.getValue() ?? "")}>{c.getValue()}</Link> }),
                    pipelineCol.accessor("runs", { header: "Runs", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    pipelineCol.accessor("success_rate", { header: "Success rate", cell: (c) => <span className="num">{percent(c.getValue())}</span> }),
                    pipelineCol.accessor("average_seconds", { header: "Average", cell: (c) => <span className="num">{seconds(c.getValue())}</span> }),
                    pipelineCol.accessor("longest_seconds", { header: "Longest", cell: (c) => <span className="num">{seconds(c.getValue())}</span> }),
                    pipelineCol.accessor("sla_breached", { header: "SLA breached", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    pipelineCol.accessor("attempts", { header: "Attempts", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    pipelineCol.accessor("retries", { header: "Retries", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    pipelineCol.accessor("lost_attempts", { header: "Lost", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    pipelineCol.accessor("rows_written", { header: "Rows written", cell: (c) => num(c.getValue()) }),
                    pipelineCol.accessor("rows_per_second", { header: "Rows per second", cell: (c) => <span className="num">{c.getValue() === null ? "Not measured" : c.getValue()?.toFixed(1)}</span> }),
                  ]}
                />
              </TablePanel>
            ) : null}
            {tab === "data" ? (
              <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(18rem,26rem)_minmax(0,1fr)]">
                <Panel title="Most rows written, by task">
                  <HBars
                    label="Rows written by task"
                    empty="No task reported rows written in this window."
                    rows={d.tasks
                      .filter((t) => t.target_rows !== null)
                      .sort((a, b) => (b.target_rows ?? 0) - (a.target_rows ?? 0))
                      .slice(0, 12)
                      .map((t): BarRow => ({ label: t.task_code, value: t.target_rows ?? 0, text: String(t.target_rows), to: pipelinePath(code, t.pipeline_code) }))}
                  />
                </Panel>
                <TablePanel
                  title="Rows by task"
                  note="Counts of successful task runs as each handler reported them; stages are not added together."
                  action={
                    <CsvButton
                      size="sm"
                      name={`${code}-insights-tasks.csv`}
                      header={["pipeline", "task", "runs", "source_rows", "target_rows", "inserted", "updated", "deleted", "rejected"]}
                      rows={d.tasks.map((t) => [t.pipeline_code, t.task_code, t.runs, t.source_rows, t.target_rows, t.inserted, t.updated, t.deleted, t.rejected])}
                    />
                  }
                >
                  <DataTable
                    label="Rows by task"
                    data={d.tasks}
                    empty="No successful task runs in this window."
                    columns={[
                      taskCol.accessor("pipeline_code", { header: "Pipeline" }),
                      taskCol.accessor("task_code", { header: "Task", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
                      taskCol.accessor("runs", { header: "Runs", cell: (c) => <span className="num">{c.getValue()}</span> }),
                      taskCol.accessor("source_rows", { header: "Source rows", cell: (c) => num(c.getValue()) }),
                      taskCol.accessor("target_rows", { header: "Target rows", cell: (c) => num(c.getValue()) }),
                      taskCol.accessor("inserted", { header: "Inserted", cell: (c) => num(c.getValue()) }),
                      taskCol.accessor("updated", { header: "Updated", cell: (c) => num(c.getValue()) }),
                      taskCol.accessor("deleted", { header: "Deleted", cell: (c) => num(c.getValue()) }),
                      taskCol.accessor("rejected", { header: "Rejected", cell: (c) => num(c.getValue()) }),
                    ]}
                  />
                </TablePanel>
              </div>
            ) : null}
            {tab === "quality" ? <Quality code={code} d={d} developer={developer} tz={tz} /> : null}
            {tab === "failures" ? (
              <TablePanel title="Failures">
                <DataTable
                  label="Failures"
                  data={d.failures}
                  empty="No failed or lost attempts in this window."
                  columns={[
                    failureCol.accessor("pipeline_code", { header: "Pipeline", cell: (c) => <Link className="font-medium text-accent hover:underline" to={pipelinePath(code, c.getValue())}>{c.getValue()}</Link> }),
                    failureCol.accessor("task_code", { header: "Task" }),
                    failureCol.accessor("status", { header: "Status", cell: (c) => <StatusBadge status={c.getValue()} /> }),
                    failureCol.accessor("failure_class", { header: "Failure class", cell: (c) => c.getValue() ?? "Unknown" }),
                    failureCol.accessor("attempts", { header: "Attempts", cell: (c) => <span className="num">{c.getValue()}</span> }),
                  ]}
                />
              </TablePanel>
            ) : null}
            {tab === "runs" ? (
              <TablePanel title="Latest runs">
                <DataTable
                  label="Latest runs"
                  data={d.latest}
                  empty="No runs in this window."
                  columns={[
                    runCol.accessor("pipeline_run_id", { header: "Run", cell: (c) => <Link className="num font-medium text-accent hover:underline" to={runPath(code, c.row.original.pipeline_code, c.getValue())}>#{c.getValue()}</Link> }),
                    runCol.accessor("pipeline_code", { header: "Pipeline" }),
                    runCol.accessor("status", { header: "Status", cell: (c) => <StatusBadge status={c.getValue()} /> }),
                    runCol.accessor("sla_status", { header: "SLA", cell: (c) => (c.getValue() ? <StatusBadge status={c.getValue() as string} /> : "") }),
                    runCol.accessor("start_date", { header: "Started", cell: (c) => when(c.getValue()) }),
                    runCol.accessor("trigger_kind", { header: "Trigger", cell: (c) => <span className="text-muted">{c.getValue().toLowerCase()}</span> }),
                  ]}
                />
              </TablePanel>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** The one-screen summary: headline numbers, then the trend and where the problems are. */
function Overview({ code, d, when }: { code: string; d: InsightsView; when: (value: string | null) => React.ReactNode }) {
  const t = d.total;
  const worst = [...d.per_pipeline].filter((p) => p.success_rate !== null).sort((a, b) => (a.success_rate ?? 0) - (b.success_rate ?? 0));
  return (
    <>
      <div className="grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <KpiTile label="Runs" value={t.runs} hint={t.in_progress ? `${t.in_progress} running now` : `${t.finished} finished`} />
        <KpiTile label="Success rate" value={percent(t.success_rate)} hint={t.failed ? `${t.failed} failed` : "none failed"} tone={t.failed ? "bad" : t.success_rate === null ? undefined : "ok"} />
        <KpiTile label="Average duration" value={seconds(t.average_seconds)} hint={t.longest_seconds === null ? undefined : `longest ${seconds(t.longest_seconds)}`} />
        <KpiTile label="SLA breached" value={t.sla_breached} tone={t.sla_breached ? "warn" : undefined} />
        <KpiTile label="Retries" value={t.retries} hint={t.lost_attempts ? `${t.lost_attempts} attempts lost` : `${t.attempts} attempts`} tone={t.lost_attempts ? "warn" : undefined} />
        <KpiTile label="Rows written" value={measured(t.rows_written)} hint={t.rows_per_second === null ? "rate not measured" : `${t.rows_per_second.toFixed(1)} rows/s`} />
      </div>
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-3 lg:grid-rows-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Runs per day" className="min-h-64 lg:col-span-2">
          {d.days.length ? <StackedBars days={d.days} /> : <p className="m-0 text-sm text-muted">No runs started in this window. Widen the range or check the pipelines&apos; schedules.</p>}
        </Panel>
        <Panel title="Success rate by pipeline" aside={<span className="text-xs text-muted">lowest first</span>} className="min-h-48">
          <HBars
            label="Success rate by pipeline"
            empty="No pipeline has a finished run in this window."
            rows={worst.slice(0, 10).map((p): BarRow => ({ label: p.pipeline_code ?? "", value: p.success_rate ?? 0, text: percent(p.success_rate), tone: (p.success_rate ?? 0) >= 0.95 ? "ok" : (p.success_rate ?? 0) >= 0.8 ? "warn" : "bad", to: pipelinePath(code, p.pipeline_code ?? "") }))}
          />
        </Panel>
        <Panel title="Average duration per day" className="min-h-48">
          <Trend days={d.days} value={(day) => day.average_seconds} format={(n) => seconds(n)} />
        </Panel>
        <Panel title="Latest runs" className="min-h-48 lg:col-span-2" aside={<Link className="text-xs text-accent hover:underline" to="?tab=runs">All runs</Link>}>
          {d.latest.length ? (
            <ul aria-label="Latest runs" className="m-0 grid min-h-0 flex-1 list-none content-start gap-1 overflow-auto p-0 text-[13px]">
              {d.latest.slice(0, 12).map((r) => (
                <li key={r.pipeline_run_id} className="grid grid-cols-[7rem_minmax(8rem,1fr)_auto] items-center gap-3 border-b border-border py-1 last:border-0">
                  <StatusBadge status={r.status} />
                  <span className="truncate">
                    <Link className="text-accent hover:underline" to={runPath(code, r.pipeline_code, r.pipeline_run_id)}>
                      {r.pipeline_code} <span className="num">#{r.pipeline_run_id}</span>
                    </Link>
                  </span>
                  <span className="text-xs text-muted">{when(r.start_date)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="m-0 text-sm text-muted">No runs in this window.</p>
          )}
        </Panel>
      </div>
    </>
  );
}

/** Rules and schema checks: what ran, what did not pass, and how far the declared tables are checked. */
function Quality({ code, d, developer, tz }: { code: string; d: InsightsView; developer: boolean; tz: string }) {
  const open = d.gaps.filter((g) => !["Matched", "Unchecked", "Not declared", "Expected before first deployment"].includes(g.state));
  const byState = new Map<string, number>();
  for (const g of d.gaps) byState.set(g.state, (byState.get(g.state) ?? 0) + g.checks);
  return (
    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,26rem)]">
      <TablePanel title="Data quality rules" note="Valid and eligible row counts are not recorded, so no quality percentage is shown.">
        <DataTable
          label="Data quality rules"
          data={d.rules}
          empty="No business rules ran in this window."
          columns={[
            ruleCol.accessor("pipeline_code", { header: "Pipeline" }),
            ruleCol.accessor("rule_name", { header: "Rule", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            ruleCol.accessor("runs", { header: "Runs", cell: (c) => <span className="num">{c.getValue()}</span> }),
            ruleCol.accessor("failed", { header: "Failed runs", cell: (c) => <span className="num">{c.getValue()}</span> }),
            ruleCol.display({ id: "passed", header: "Passed / not passed", cell: (c) => <span className="num">{c.row.original.passed} / {c.row.original.not_passed}</span> }),
            ruleCol.accessor("flagged_rows", { header: "Rows flagged", cell: (c) => <span className="num">{c.getValue()}</span> }),
            ruleCol.display({
              id: "observed",
              header: "Newest observed values",
              cell: (c) =>
                c.row.original.observations.length ? <span className="font-mono text-xs">{c.row.original.observations.map((o) => `${o.observed}${o.passed === "N" ? " ✕" : ""}`).join(", ")}</span> : <span className="text-muted">None</span>,
            }),
          ]}
        />
      </TablePanel>
      <Panel
        title="Schema and lineage checks"
        aside={
          developer && d.schema_check_on_demand ? (
            <ActionButton<{ message?: string }> code={code} label="Check now" title="Check the declared tables against the warehouse" effect="Compares the declared tables with the warehouse and rebuilds the catalog." endpoint="/docs" body={() => ({ with_warehouse: true })} askReason={false} describe={(r) => r.message ?? "The check was requested."} size="sm" />
          ) : null
        }
      >
        <p className="mb-2 mt-0 text-[13px]">
          {d.gaps_compared_at ? `Last warehouse check ${formatTime(d.gaps_compared_at, tz)}.` : <strong>Not checked against the warehouse yet: most states read Unchecked.</strong>}{" "}
          {open.length ? (
            <Link className="text-accent hover:underline" to={catalogPath(code, "gaps")}>
              {open.length} open gap{open.length === 1 ? "" : "s"}
            </Link>
          ) : (
            "No open gaps."
          )}
        </p>
        <HBars label="Checks by state" empty="No declared tables to check." rows={[...byState.entries()].sort((a, b) => b[1] - a[1]).map(([state, checks]): BarRow => ({ label: state, value: checks, tone: ["Matched", "Unchecked", "Not declared", "Expected before first deployment"].includes(state) ? "accent" : "warn" }))} />
        <p className="mb-0 mt-2 text-xs text-muted">
          Scheduled checks: {d.schema_check_schedule ? <code className="font-mono">{d.schema_check_schedule}</code> : "not scheduled"}. Unchecked and unavailable comparisons are never counted as matched.
        </p>
      </Panel>
    </div>
  );
}
