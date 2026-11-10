import { Disclosure, DisclosureSummary } from "@/components/dropdown";
import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import * as React from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, Navigate, useLocation, useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { CsvButton } from "@/components/csv-button";
import { EmptyState, Field, inputClass, Loading, Notice, PageHeader } from "@/components/common";
import { CatalogInsights } from "@/components/catalog-insights";
import { DataTable } from "@/components/data-table";
import { HBars, KpiTile, Panel, type BarRow } from "@/components/charts";
import { Overview } from "@/components/overview";
import { Tabs } from "@/components/tabs";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useProjectInfo, useRoleAtLeast } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { useCatalog } from "@/lib/catalog";
import { measured, percent, seconds } from "@/lib/format";
import { catalogPath, pipelinePath } from "@/lib/routes";
import type { AgentsView, FailureInsight, Insights as InsightsView, Pipeline, PipelineInsight, RuleInsight, TaskInsight } from "@/lib/types";
import { projectHomePath } from "@/lib/routes";
import { useDocumentTitle } from "@/title";

const pipelineCol = createColumnHelper<PipelineInsight>();
const taskCol = createColumnHelper<TaskInsight>();
const failureCol = createColumnHelper<FailureInsight>();
const ruleCol = createColumnHelper<RuleInsight>();
const num = (v: number | null) => <span className="num">{measured(v)}</span>;

/** The old address of this page: Home is the project's insights, so it opens Home with its filters. */
export function InsightsRedirect() {
  const { project = "" } = useParams();
  const { search } = useLocation();
  return <Navigate to={projectHomePath(project) + search} replace />;
}

/** The catalog's coverage and open gaps, read from the last build. */
function CatalogTab({ code }: { code: string }) {
  const built = useCatalog(code);
  if (built.isPending) return <Loading what="the catalog" className="p-3" />;
  if (built.isError) return <Notice className="m-3">{(built.error as Error).message} Rebuild the catalog from the Catalog page.</Notice>;
  return <CatalogInsights code={code} doc={built.data} />;
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
        <Panel title="CPU in use by pool"><HBars label="CPU in use by pool" rows={cpu} empty="No pools yet. Add a pool in Administration to track resource use." /></Panel>
        <Panel title="Memory in use by pool"><HBars label="Memory in use by pool" rows={memory} empty="No pools yet. Add a pool in Administration to track resource use." /></Panel>
      </div>
    </div>
  );
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "capacity", label: "Capacity" },
  { id: "catalog", label: "Catalog" },
  { id: "pipelines", label: "Pipelines" },
  { id: "data", label: "Data" },
  { id: "quality", label: "Quality" },
  { id: "failures", label: "Failures" },
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
  const activePreset = !from && !to ? "7" : RANGES.find((r) => from === isoDay(today - (r.days - 1) * 86_400_000) && !to)?.id;
  const togglePipeline = (name: string) =>
    change((next) => {
      const now = next.getAll("pipeline");
      next.delete("pipeline");
      (now.includes(name) ? now.filter((c) => c !== name) : [...now, name]).forEach((c) => next.append("pipeline", c));
    });
  const d = found.data;
  const total = d?.total;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <PageHeader back={null}
        compact
        title="Home"
        subtitle={d ? <>Runs started <When iso={d.window_start} /> to <When iso={d.window_end} /></> : undefined}
        actions={
          <div className="flex flex-wrap items-end justify-end gap-2">
            <div role="group" aria-label="Time range" className="inline-flex h-8 items-center rounded-md bg-surface-2 p-0.5 text-[13px] max-sm:h-11">
              {RANGES.map((r) => (
                <button key={r.id} type="button" aria-pressed={activePreset === r.id} onClick={() => preset(r.days)} className={cn("h-7 cursor-pointer rounded-[5px] px-3 max-sm:h-10", activePreset === r.id ? "bg-surface font-medium text-fg shadow-raised" : "text-muted hover:text-fg")}>
                  {r.label}
                </button>
              ))}
            </div>
            <Disclosure className="relative">
              <DisclosureSummary className="flex h-8 cursor-pointer list-none items-center rounded-md bg-surface px-3 text-[13px] font-medium shadow-raised hover:bg-surface-2 max-sm:h-11">
                {from || to ? `${from || "start"} to ${to || "today"}` : "Custom range"}
              </DisclosureSummary>
              <div className="absolute right-0 z-30 mt-1.5 flex gap-3 rounded-xl bg-surface p-3 shadow-pop">
                <Field compact label="From (UTC day)">
                  <input type="date" value={from} onChange={(event) => set("from", event.target.value)} className={cn(inputClass, "w-36")} />
                </Field>
                <Field compact label="To (UTC day)">
                  <input type="date" value={to} onChange={(event) => set("to", event.target.value)} className={cn(inputClass, "w-36")} />
                </Field>
              </div>
            </Disclosure>
            <Disclosure className="relative">
              <DisclosureSummary className="flex h-8 cursor-pointer list-none items-center rounded-md bg-surface px-3 text-[13px] font-medium shadow-raised hover:bg-surface-2 max-sm:h-11">
                Pipelines {chosen.length ? `(${chosen.length} selected)` : "(all you can view)"}
              </DisclosureSummary>
              <fieldset className="absolute right-0 z-30 mt-1 grid max-h-72 min-w-64 gap-1 overflow-auto rounded-xl bg-surface p-3 shadow-pop">
                <legend className="sr-only">Pipelines</legend>
                {(choices.data?.pipelines ?? []).map((p) => (
                  <label key={p.pipeline_code} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={chosen.includes(p.pipeline_code)} onChange={() => togglePipeline(p.pipeline_code)} /> {p.pipeline_code}
                  </label>
                ))}
              </fieldset>
            </Disclosure>
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
            {tab === "catalog" ? <CatalogTab code={code} /> : null}
            {tab === "overview" ? <div className="min-h-0 flex-1 overflow-auto"><Overview code={code} d={d} /></div> : null}
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
                <DataTable find
                  label="Pipelines"
                  data={d.per_pipeline}
                  empty={<EmptyState title="No pipeline ran in this window.">Choose a wider time range or run a pipeline.</EmptyState>}
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
                    empty="No task reported rows written. Choose a wider time range; counts appear when a handler reports them."
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
                  <DataTable find
                    label="Rows by task"
                    data={d.tasks}
                    empty={<EmptyState title="No successful task runs in this window.">Choose a wider time range or inspect failed runs.</EmptyState>}
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
            {tab === "quality" ? <Quality code={code} d={d} developer={developer} /> : null}
            {tab === "failures" ? (
              <TablePanel title="Failures">
                <DataTable find
                  label="Failures"
                  data={d.failures}
                  empty={<EmptyState title="No failed or lost attempts in this window.">Choose a wider time range to inspect earlier failures.</EmptyState>}
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
          </div>
        </>
      ) : null}
    </div>
  );
}

/** Rules and schema checks: what ran, what did not pass, and how far the declared tables are checked. */
function Quality({ code, d, developer }: { code: string; d: InsightsView; developer: boolean }) {
  const open = d.gaps.filter((g) => !["Matched", "Unchecked", "Not declared", "Expected before first deployment"].includes(g.state));
  const byState = new Map<string, number>();
  for (const g of d.gaps) byState.set(g.state, (byState.get(g.state) ?? 0) + g.checks);
  return (
    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,26rem)]">
      <TablePanel title="Data quality rules" note="Valid and eligible row counts are not recorded, so no quality percentage is shown.">
        <DataTable find
          label="Data quality rules"
          data={d.rules}
          empty={<EmptyState title="No business rules ran in this window.">Configure business rules for a data task, then run its pipeline.</EmptyState>}
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
          {d.gaps_compared_at ? <>Last warehouse check <When iso={d.gaps_compared_at} />.</> : <strong>Not checked against the warehouse yet: most states read Unchecked.</strong>}{" "}
          {open.length ? (
            <Link className="text-accent hover:underline" to={catalogPath(code, "gaps")}>
              {open.length} open gap{open.length === 1 ? "" : "s"}
            </Link>
          ) : (
            "No open gaps."
          )}
        </p>
        <HBars label="Checks by state" empty="No declared tables to check. Declare columns in config files, then rebuild the catalog." rows={[...byState.entries()].sort((a, b) => b[1] - a[1]).map(([state, checks]): BarRow => ({ label: state, value: checks, tone: ["Matched", "Unchecked", "Not declared", "Expected before first deployment"].includes(state) ? "accent" : "warn" }))} />
        <p className="mb-0 mt-2 text-xs text-muted">
          Scheduled checks: {d.schema_check_schedule ? <code className="font-mono">{d.schema_check_schedule}</code> : "not scheduled"}. Unchecked and unavailable comparisons are never counted as matched.
        </p>
      </Panel>
    </div>
  );
}
