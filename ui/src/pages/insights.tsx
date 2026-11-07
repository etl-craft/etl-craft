import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, Navigate, useLocation, useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { CsvButton } from "@/components/csv-button";
import { Field, FactList, inputClass, Loading, Notice, PageHeader, Stat } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { DayBars } from "@/components/day-bars";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectInfo, useRoleAtLeast, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatTime, measured, percent, seconds } from "@/lib/format";
import { catalogPath, pipelinePath, runPath } from "@/lib/routes";
import type { DayInsight, FailureInsight, GapInsight, Insights as InsightsView, Pipeline, PipelineInsight, RuleInsight, RunView, TaskInsight } from "@/lib/types";
import { projectHomePath } from "@/lib/routes";
import { useDocumentTitle } from "@/title";

const pipelineCol = createColumnHelper<PipelineInsight>();
const taskCol = createColumnHelper<TaskInsight>();
const failureCol = createColumnHelper<FailureInsight>();
const ruleCol = createColumnHelper<RuleInsight>();
const gapCol = createColumnHelper<GapInsight>();
const runCol = createColumnHelper<RunView>();
const dayCol = createColumnHelper<DayInsight>();
const num = (v: number | null) => <span className="num">{measured(v)}</span>;

/** The old address of this page: Home is the project's insights, so it opens Home with its filters. */
export function InsightsRedirect() {
  const { project = "" } = useParams();
  const { search } = useLocation();
  return <Navigate to={projectHomePath(project) + search} replace />;
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
  const choices = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`) });
  const found = useQuery({
    queryKey: ["insights", code, from, to, chosen],
    queryFn: () => getJson<InsightsView>(`${project(code)}/insights`, { start: from, end: to, pipelines: chosen }),
    refetchInterval: 30_000,
  });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const togglePipeline = (name: string) => {
    const next = new URLSearchParams(params);
    next.delete("pipeline");
    (chosen.includes(name) ? chosen.filter((c) => c !== name) : [...chosen, name]).forEach((c) => next.append("pipeline", c));
    setParams(next, { replace: true });
  };
  const d = found.data;
  const total = d?.total;
  const when = (value: string | null) => <span className="num whitespace-nowrap">{formatTime(value, tz)}</span>;

  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader
        title="Home"
        subtitle={d ? `Runs started from ${formatTime(d.window_start, tz)} up to ${formatTime(d.window_end, tz)}. Rates use finished runs; counts a task did not report are shown as Not measured, never 0.` : code}
      >
        <div className="flex flex-wrap items-end gap-3">
          <Field compact label="From (UTC day)">
            <input type="date" value={from} onChange={(event) => set("from", event.target.value)} className={inputClass} />
          </Field>
          <Field compact label="To (UTC day)">
            <input type="date" value={to} onChange={(event) => set("to", event.target.value)} className={inputClass} />
          </Field>
          <details className="relative">
            <summary className="flex h-9 cursor-pointer items-center rounded-md border border-border-strong bg-surface px-3 text-sm max-sm:h-11">
              Pipelines {chosen.length ? `(${chosen.length} selected)` : "(all you can view)"}
            </summary>
            <fieldset className="absolute z-20 mt-1 grid max-h-72 min-w-64 gap-1 overflow-auto rounded-md border border-border bg-surface p-3 shadow-lg">
              <legend className="sr-only">Pipelines</legend>
              {(choices.data?.pipelines ?? []).map((p) => (
                <label key={p.pipeline_code} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={chosen.includes(p.pipeline_code)} onChange={() => togglePipeline(p.pipeline_code)} /> {p.pipeline_code}
                </label>
              ))}
            </fieldset>
          </details>
        </div>
      </PageHeader>
      {found.isError ? <Notice>{(found.error as Error).message}</Notice> : null}
      {found.isPending ? <Loading what="insights" /> : null}
      {d && total ? (
        <>
          <Card className="p-4">
            <FactList className="gap-y-5 lg:grid-cols-4">
              <Stat label="Runs" value={total.runs} />
              <Stat label="Success rate" value={percent(total.success_rate)} />
              <Stat label="Average duration" value={seconds(total.average_seconds)} />
              <Stat label="SLA breached" value={total.sla_breached} tone={total.sla_breached ? "text-warn" : "text-muted"} />
              <Stat label="Retries" value={total.retries} />
              <Stat label="Average wait to start" value={seconds(total.average_wait_seconds)} />
              <Stat label="Average execution" value={seconds(total.average_run_seconds)} />
              <Stat label="Rows written" value={measured(total.rows_written)} />
            </FactList>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Runs per day</CardTitle>
              <span className="flex items-center gap-3 text-xs text-muted">
                <span><span className="mr-1 inline-block size-2 bg-ok" aria-hidden />Succeeded</span>
                <span><span className="mr-1 inline-block size-2 bg-bad" aria-hidden />Failed</span>
                <span><span className="mr-1 inline-block size-2 bg-idle-bg" aria-hidden />Running, skipped or cancelled</span>
              </span>
            </CardHeader>
            {d.days.length ? (
              <>
                <div className="p-4">
                  <DayBars days={d.days} />
                </div>
                <DataTable
                  label="Runs per day"
                  data={d.days}
                  columns={[
                    dayCol.accessor("day", { header: "Day (UTC)" }),
                    dayCol.accessor("runs", { header: "Runs", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    dayCol.accessor("succeeded", { header: "Succeeded", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    dayCol.accessor("failed", { header: "Failed", cell: (c) => <span className="num">{c.getValue()}</span> }),
                    dayCol.accessor("average_seconds", { header: "Average duration", cell: (c) => <span className="num">{seconds(c.getValue())}</span> }),
                  ]}
                />
              </>
            ) : (
              <p className="m-0 p-4 text-muted">No runs started in this window. Widen the window or check the pipelines&apos; schedules.</p>
            )}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Pipelines</CardTitle>
              <CsvButton
                size="sm"
                name={`${code}-insights-pipelines.csv`}
                header={["pipeline", "runs", "success_rate", "average_seconds", "longest_seconds", "sla_breached", "attempts", "retries", "lost", "rows_written", "rows_per_second"]}
                rows={d.per_pipeline.map((p) => [p.pipeline_code, p.runs, p.success_rate, p.average_seconds, p.longest_seconds, p.sla_breached, p.attempts, p.retries, p.lost_attempts, p.rows_written, p.rows_per_second])}
              />
            </CardHeader>
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
          </Card>

          <Card>
            <CardHeader>
              <div className="grid">
                <CardTitle>Rows by task</CardTitle>
                <span className="text-xs text-muted">Counts of successful task runs as each handler reported them; stages are not added together.</span>
              </div>
              <CsvButton
                size="sm"
                name={`${code}-insights-tasks.csv`}
                header={["pipeline", "task", "runs", "source_rows", "target_rows", "inserted", "updated", "deleted", "rejected"]}
                rows={d.tasks.map((t) => [t.pipeline_code, t.task_code, t.runs, t.source_rows, t.target_rows, t.inserted, t.updated, t.deleted, t.rejected])}
              />
            </CardHeader>
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
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Failures</CardTitle>
            </CardHeader>
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
          </Card>

          <Card>
            <CardHeader>
              <div className="grid">
                <CardTitle>Data quality rules</CardTitle>
                <span className="text-xs text-muted">Valid and eligible row counts are not recorded, so no quality percentage is shown.</span>
              </div>
            </CardHeader>
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
                    c.row.original.observations.length ? (
                      <span className="font-mono text-xs">{c.row.original.observations.map((o) => `${o.observed}${o.passed === "N" ? " ✕" : ""}`).join(", ")}</span>
                    ) : (
                      <span className="text-muted">None</span>
                    ),
                }),
              ]}
            />
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Schema and lineage checks</CardTitle>
              {developer && d.schema_check_on_demand ? (
                <ActionButton<{ message?: string }>
                  code={code}
                  label="Check now"
                  title="Check the declared tables against the warehouse"
                  effect="Compares the declared tables with the warehouse and rebuilds the catalog."
                  endpoint="/docs"
                  body={() => ({ with_warehouse: true })}
                  askReason={false}
                  describe={(r) => r.message ?? "The check was requested."}
                  size="sm"
                />
              ) : null}
            </CardHeader>
            <div className="grid gap-2 p-4 text-[13px]">
              <p className="m-0">
                {d.gaps_compared_at ? `Last warehouse check: ${formatTime(d.gaps_compared_at, tz)}.` : <strong>Not checked against the warehouse yet: these states come from the declared metadata only, so most read Unchecked.</strong>}{" "}
                Scheduled checks: {d.schema_check_schedule ? <code className="font-mono">{d.schema_check_schedule}</code> : "not scheduled; an administrator sets one with etl-craft project set --schema-check-schedule"}.
              </p>
              {!d.schema_check_on_demand ? <p className="m-0 text-muted">On-demand checks are off for this project; it is checked only on its schedule.</p> : null}
            </div>
            <DataTable
              label="Schema and lineage checks"
              data={d.gaps}
              empty="No declared tables to check."
              columns={[
                gapCol.accessor("attribute", { header: "Attribute" }),
                gapCol.accessor("state", { header: "State" }),
                gapCol.accessor("checks", { header: "Checks", cell: (c) => <span className="num">{c.getValue()}</span> }),
              ]}
            />
            <p className="m-0 border-t border-border px-4 py-3 text-xs text-muted">
              Unchecked and unavailable comparisons are never counted as matched. <Link className="text-accent hover:underline" to={catalogPath(code)}>Open the catalog</Link> for each gap.
            </p>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Latest runs</CardTitle>
            </CardHeader>
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
          </Card>
        </>
      ) : null}
    </div>
  );
}
