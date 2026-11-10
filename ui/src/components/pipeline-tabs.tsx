import { Disclosure, DisclosureSummary } from "@/components/dropdown";
import { useQueries, useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import * as React from "react";
import { Link } from "react-router-dom";
import { Fact, FactList, Loading, Notice, SelectField } from "@/components/common";
import { RunBars } from "@/components/pipeline-parts";
import { isFailure, StatusBadge, taskStatus, toneClass } from "@/components/status";
import { columnsOf, DataTable } from "@/components/data-table";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatSeconds } from "@/lib/format";
import { handlerLabel } from "@/lib/labels";
import { catalogPath, taskPath } from "@/lib/routes";
import type { AuditRecords, Graph, Pipeline, RunView, Steps, TaskDefinition } from "@/lib/types";
import { cn } from "@/lib/utils";

const WINDOWS: Record<string, { label: string; hours: number }> = {
  "24h": { label: "Last 24 hours", hours: 24 },
  "7d": { label: "Last 7 days", hours: 24 * 7 },
  "30d": { label: "Last 30 days", hours: 24 * 30 },
};

const seconds = (run: RunView) => (run.start_date && run.end_date ? (new Date(run.end_date).getTime() - new Date(run.start_date).getTime()) / 1000 : null);

function Tile({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "bad" }) {
  return (
    <div data-card className="grid gap-1 rounded-sm border border-border bg-surface p-3">
      <span className="text-xs text-muted">{label}</span>
      <span className={tone === "bad" ? "text-2xl font-semibold text-bad" : "text-2xl font-semibold"}>{value}</span>
    </div>
  );
}

/** The pipeline over a window: how many runs, how many failed, how long they took, and the newest durations. */
export function OverviewTab({ code, pipeline, runs }: { code: string; pipeline: Pipeline; runs: RunView[] }) {
  const [window, setWindow] = React.useState("24h");
  const [now] = React.useState(() => Date.now());
  const since = now - WINDOWS[window]!.hours * 3_600_000;
  const inWindow = runs.filter((run) => run.start_date && new Date(run.start_date).getTime() >= since);
  const failed = inWindow.filter((run) => run.status === "FAILED" || run.status === "LOST");
  const done = inWindow.map(seconds).filter((s): s is number => s !== null).sort((a, b) => a - b);
  const median = done.length ? done[Math.floor(done.length / 2)]! : null;
  const finished = inWindow.filter((run) => run.end_date);
  const rate = finished.length ? Math.round((finished.filter((run) => run.status === "SUCCESS").length / finished.length) * 100) : null;
  return (
    <div className="grid gap-4">
      <SelectField compact label="Window" value={window} onChange={setWindow}>
        {Object.entries(WINDOWS).map(([id, w]) => (
          <option key={id} value={id}>
            {w.label}
          </option>
        ))}
      </SelectField>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Runs" value={inWindow.length} />
        <Tile label="Failed runs" value={failed.length} tone={failed.length ? "bad" : undefined} />
        <Tile label="Success rate" value={rate === null ? "—" : `${rate}%`} />
        <Tile label="Median duration" value={median === null ? "—" : formatSeconds(median)} />
      </div>
      <section className="grid gap-2" aria-label="Latest run durations">
        <h3 className="m-0 text-sm font-semibold">{runs.length === 1 ? "The only run" : `Last ${Math.min(10, runs.length)} runs`}</h3>
        {runs.length >= 5 ? (
          <RunBars project={code} runs={runs.slice(0, 10)} />
        ) : runs.length ? (
          // A few runs are listed with their durations; a chart of two bars says less.
          <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
            {runs.map((run) => (
              <li key={run.pipeline_run_id} className="flex flex-wrap items-center gap-2">
                <StatusBadge status={run.status} />
                <Link className="num text-accent hover:underline" to={`/projects/${encodeURIComponent(code)}/pipelines/${encodeURIComponent(run.pipeline_code)}?run=${run.pipeline_run_id}`}>#{run.pipeline_run_id}</Link>
                <span className="num text-muted">{formatDuration(run.start_date, run.end_date)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-muted">No runs yet.</p>
        )}
      </section>
      <section className="grid gap-2" aria-label="Recent failures">
        <h3 className="m-0 text-sm font-semibold">Recent failures</h3>
        {failed.length === 0 ? (
          <p className="m-0 text-muted">No failed runs in this window.</p>
        ) : (
          <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
            {failed.slice(0, 8).map((run) => (
              <li key={run.pipeline_run_id} className="flex flex-wrap items-center gap-2">
                <StatusBadge status={run.status} />
                <Link className="num text-accent hover:underline" to={`/projects/${encodeURIComponent(code)}/pipelines/${encodeURIComponent(pipeline.pipeline_code)}?run=${run.pipeline_run_id}`}>
                  #{run.pipeline_run_id}
                </Link>
                <span className="text-muted">{formatDuration(run.start_date, run.end_date)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Each task's definition, read once and shared by the tabs that list tasks. */
export function useTaskDefinitions(code: string, pipeline: string, tasks: string[]) {
  const results = useQueries({
    queries: tasks.map((task) => ({
      queryKey: ["task", code, pipeline, task],
      queryFn: () => getJson<TaskDefinition>(`${project(code)}/task`, { pipeline_code: pipeline, task_code: task }),
      staleTime: 60_000,
    })),
  });
  return { definitions: new Map(tasks.map((task, i) => [task, results[i]?.data])), loading: results.some((r) => r.isPending), error: results.find((r) => r.isError)?.error as Error | undefined };
}

/** Every task of the pipeline with its handler, what it waits for, and its state in the selected run. */
export function TasksTab({ code, pipeline, graph, runId, run }: { code: string; pipeline: string; graph: Graph; runId?: number; run?: RunView }) {
  const tasks = graph.waves.flat();
  const { definitions, loading, error } = useTaskDefinitions(code, pipeline, tasks);
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, runId],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: runId }),
    enabled: runId !== undefined,
  });
  const status = new Map((steps.data?.steps ?? []).map((s) => [s.task_code, taskStatus(s.status, run)]));
  return (
    <div className="grid gap-3">
      {error ? <Notice>{error.message}</Notice> : null}
      {loading ? <Loading what="tasks" /> : null}
      <div data-card className="overflow-hidden rounded-sm border border-border">
        <DataTable
          label="Pipeline tasks"
          data={tasks}
          columns={columnsOf<string>([
            { id: "task", header: "Task", value: (t) => t, size: 280, cell: (t) => <Link className="font-medium text-accent hover:underline" to={taskPath(code, pipeline, t)}>{t}</Link> },
            { id: "handler", header: "Handler", value: (t) => definitions.get(t)?.handler ?? "", size: 130, cell: (t) => (definitions.get(t) ? handlerLabel(definitions.get(t)?.handler) : "…") },
            { id: "waits", header: "Waits for", value: (t) => (graph.depends_on[t] ?? []).map(([upstream]) => upstream).join(", "), size: 320, cell: (t) => <span className="text-muted">{(graph.depends_on[t] ?? []).map(([upstream]) => upstream).join(", ") || "—"}</span> },
            ...(runId !== undefined ? [{ id: "state", header: `Run #${runId}`, value: (t: string) => status.get(t) ?? "", size: 150, cell: (t: string) => (status.has(t) ? <StatusBadge quiet status={status.get(t)!} /> : "—") }] : []),
          ])}
        />
      </div>
    </div>
  );
}

/** The pipeline as its files define it: its settings, then each task's handler and parameters. What the pipeline and its tasks are for is documented in the catalog. */
export function DetailsTab({ code, pipeline, graph }: { code: string; pipeline: Pipeline; graph?: Graph }) {
  const tasks = graph ? graph.waves.flat() : [];
  const { definitions, loading, error } = useTaskDefinitions(code, pipeline.pipeline_code, tasks);
  return (
    <div className="grid gap-4">
      <FactList className="sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Pipeline">{pipeline.pipeline_code}</Fact>
        <Fact label="Name">{pipeline.pipeline_name}</Fact>
        <Fact label="Refresh">{pipeline.refresh_type.toLowerCase()}</Fact>
        <Fact label="Schedule">{pipeline.run_schedule ? <code className="font-mono">{pipeline.run_schedule}</code> : "Not scheduled"}</Fact>
        <Fact label="Restarts">{pipeline.restart_note ?? "On its schedule only"}</Fact>
        <Fact label="Next run"><When iso={pipeline.next_run} empty={pipeline.schedule_problem ?? "—"} /></Fact>
        <Fact label="SLA">{pipeline.sla_in_hours ? `${pipeline.sla_in_hours} h` : "None"}</Fact>
        <Fact label="Automatic runs">{pipeline.paused ? `Paused by ${pipeline.paused.paused_by}: ${pipeline.paused.reason}` : "On"}</Fact>
        <Fact label="Tasks">{tasks.length}</Fact>
        <Fact label="Tags">{pipeline.tags.length ? pipeline.tags.join(", ") : "None"}</Fact>
      </FactList>
      <p className="m-0 text-[13px]">
        <Link className="text-accent hover:underline" to={catalogPath(code, "pipelines", pipeline.pipeline_code)}>
          Open the documentation in the catalog
        </Link>
        <span className="text-muted"> for what this pipeline and its tasks do, what they read and write, and their lineage.</span>
      </p>
      <section className="grid gap-2" aria-label="Task definitions">
        <h3 className="m-0 text-sm font-semibold">Task definitions</h3>
        {error ? <Notice>{error.message}</Notice> : null}
        {loading ? <Loading what="task definitions" /> : null}
        {tasks.map((task) => {
          const def = definitions.get(task);
          return (
            <Disclosure key={task} className="rounded-md border border-border">
              <DisclosureSummary className="cursor-pointer px-3 py-2 text-[13px] font-medium">
                {task} <span className="font-normal text-muted">{handlerLabel(def?.handler)}</span>
              </DisclosureSummary>
              <dl className="m-0 grid gap-x-4 gap-y-1 border-t border-border p-3 text-xs sm:grid-cols-[max-content_1fr]">
                {Object.entries(def?.parameters ?? {}).map(([name, value]) => (
                  <React.Fragment key={name}>
                    <dt className="font-mono text-muted">{name}</dt>
                    <dd className="m-0 whitespace-pre-wrap break-words font-mono">{value}</dd>
                  </React.Fragment>
                ))}
              </dl>
            </Disclosure>
          );
        })}
      </section>
    </div>
  );
}

const DAY = 86_400_000;
const WEEKS = 12;
const day = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/** Runs by day over twelve weeks, each day coloured by its worst run: a gap in a column shows where nothing ran. */
export function CalendarTab({ runs }: { runs: RunView[] }) {
  const [today] = React.useState(() => Date.now());
  const byDay = new Map<string, RunView[]>();
  for (const run of runs) if (run.start_date) byDay.set(run.start_date.slice(0, 10), [...(byDay.get(run.start_date.slice(0, 10)) ?? []), run]);
  // Until runs cover five days, twelve weeks of empty squares hide them: the days are listed instead.
  if (byDay.size < 5)
    return (
      <div className="grid gap-2">
        <p className="m-0 text-[13px] text-muted">{byDay.size ? `Runs on ${byDay.size} day${byDay.size === 1 ? "" : "s"} so far; the calendar appears once runs cover five days.` : "No runs yet."}</p>
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

/** What was done to this pipeline: the commands run on it and the metadata changes to it. */
export function AuditTab({ code, pipeline }: { code: string; pipeline: string }) {
  const audit = useQuery({ queryKey: ["audit", code, pipeline], queryFn: () => getJson<AuditRecords>(`${project(code)}/audit`, { pipeline_code: pipeline }) });
  if (audit.isError) return <Notice>{(audit.error as Error).message}</Notice>;
  if (!audit.data) return <Loading what="the audit log" />;
  const { actions } = audit.data;
  // Many edits made together (a config apply) are one line with a count, not one line each.
  const grouped = new Map<string, { change: (typeof audit.data.changes)[number]; count: number }>();
  for (const c of audit.data.changes) {
    const key = `${c.at.slice(0, 16)}|${c.actor}|${c.table_name}|${c.operation}`;
    const found = grouped.get(key);
    if (found) found.count += 1;
    else grouped.set(key, { change: c, count: 1 });
  }
  const changes = [...grouped.values()];
  return (
    <div className="grid gap-4">
      <section className="grid gap-2" aria-label="Commands">
        <h3 className="m-0 text-sm font-semibold">Commands ({actions.length})</h3>
        {actions.length ? (
          <DataTable
            label="Commands run on this pipeline"
            data={actions.slice(0, 50)}
            columns={columnsOf<(typeof actions)[number]>([
              { id: "when", header: "When", value: (a) => a.at, size: 200, cell: (a) => <When iso={a.at} /> },
              { id: "who", header: "Who", value: (a) => a.actor, size: 160 },
              { id: "command", header: "Command", value: (a) => a.command, size: 320 },
              { id: "outcome", header: "Outcome", value: (a) => a.outcome, size: 140, cell: (a) => <span className="text-muted">{a.outcome.toLowerCase()}</span> },
            ])}
          />
        ) : (
          <p className="m-0 text-muted">No command has been recorded for this pipeline.</p>
        )}
      </section>
      <section className="grid gap-2" aria-label="Metadata changes">
        <h3 className="m-0 text-sm font-semibold">Metadata changes ({audit.data.changes.length})</h3>
        {changes.length ? (
          <DataTable
            label="Metadata changes"
            data={changes.slice(0, 50)}
            columns={columnsOf<(typeof changes)[number]>([
              { id: "when", header: "When", value: (g) => g.change.at, size: 200, cell: (g) => <When iso={g.change.at} /> },
              { id: "who", header: "Who", value: (g) => g.change.actor, size: 160 },
              { id: "table", header: "Table", value: (g) => g.change.table_name, size: 280, cell: (g) => <span className="font-mono text-xs">{g.change.table_name}</span> },
              { id: "change", header: "Change", value: (g) => g.change.operation, size: 140, cell: (g) => <span className="text-muted">{g.change.operation.toLowerCase()}</span> },
              { id: "count", header: "Rows", value: (g) => g.count, size: 90 },
            ])}
          />
        ) : (
          <p className="m-0 text-muted">No metadata change has been recorded for this pipeline.</p>
        )}
      </section>
    </div>
  );
}
