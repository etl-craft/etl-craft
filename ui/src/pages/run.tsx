import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { copyRunLabel } from "@/components/run-label";
import { controlAnswers } from "@/components/scope-controls";
import { useToast } from "@/components/toast";
import { Breadcrumbs, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { OptionalTask } from "@/components/dependency-mark";
import { columnsOf, DataTable } from "@/components/data-table";
import { RunGraph } from "@/components/lazy-run-graph";
import { RunRecovery } from "@/components/run-recovery";
import { RunFacts, TaskDetails } from "@/components/run-overview";
import { RunTimeline } from "@/components/run-timeline";
import { StatusBadge, isFailure, statusMeta, taskStatus } from "@/components/status";
import { ChecklistFilter } from "@/components/tag-filter";
import { Tabs } from "@/components/tabs";
import { Button } from "@/components/ui/button";
import { When, useNow } from "@/components/when";
import { useProjectInfo } from "@/hooks";
import { getJson, getText, project } from "@/lib/api";
import { dependencyWaves } from "@/lib/dependency-waves";
import { formatDuration } from "@/lib/format";
import { handlerLabel } from "@/lib/labels";
import { pipelineRunPath } from "@/lib/routes";
import type { Capabilities, ControlView, Graph, RunView, Steps, TaskRunView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const views = [
  { id: "graph", label: "Graph" }, { id: "list", label: "List" },
  { id: "gantt", label: "Gantt" }, { id: "events", label: "Events" },
];
const eventLabels: Record<string, string> = {
  RUN_STARTED: "Run started", RUN_ENDED: "Run ended",
  TASK_QUEUED: "Task queued", TASK_ADMITTED: "Task admitted", TASK_STARTED: "Task started",
  TASK_RETRY_DUE: "Task retried", TASK_ENDED: "Task ended", TASK_LOST: "Task lost",
  CONTROL_REQUESTED: "Control requested", CONTROL_ACKNOWLEDGED: "Control acknowledged",
  CONTROL_COMPLETED: "Control completed", INTERVENTION: "Operator intervention",
};
const live = (run?: RunView) => run && !run.end_date && ["QUEUED", "IN-PROGRESS"].includes(run.status) ? 5_000 : false;

type RunStatusView = {
  tasks: {
    task_code: string;
    status: string | null;
    explanation: {
      task: TaskRunView | null;
      condition_met: boolean | null;
      run_condition: string;
      dependencies: { upstream: string; dependency_type: string; status: string | null; met: boolean }[];
    };
  }[];
  blocked_by_failures: string[];
};

export function RunPage() {
  const { project: code = "", pipeline = "", runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const task = params.get("task");
  const view = views.find((item) => item.id === params.get("view"))?.id ?? "graph";
  const [critical, setCritical] = useState(false);
  const base = project(code);
  const toast = useToast();
  const run = useQuery({
    queryKey: ["run-reference", code, runId],
    queryFn: () => getJson<RunView>(`${base}/runs/${encodeURIComponent(runId)}`),
    refetchInterval: (query) => live(query.state.data),
  });
  const data = run.data;
  const id = data?.pipeline_run_id;
  const selection = { pipeline_code: pipeline, run_id: id };
  const addressed = id !== undefined && data?.pipeline_code === pipeline;
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, id, data?.end_date],
    queryFn: () => getJson<Steps>(`${base}/steps`, selection),
    enabled: addressed,
    refetchInterval: () => live(data),
  });
  const status = useQuery({
    queryKey: ["run-status", code, pipeline, id, data?.end_date],
    queryFn: () => getJson<RunStatusView>(`${base}/status`, selection),
    enabled: addressed,
    refetchInterval: () => live(data),
  });
  const info = useProjectInfo(code).project;
  useDocumentTitle(`${pipeline} #${id ?? runId}`, code, info && { type: info.environment_type, name: info.environment_name });
  function selectTask(name: string | null, firstError = false, attemptNumber?: number) {
    const next = new URLSearchParams(params);
    next.delete("try");
    next.delete("taskTab");
    next.delete("error");
    if (name) next.set("task", name);
    else next.delete("task");
    if (firstError) next.set("error", "first");
    if (attemptNumber !== undefined) next.set("try", String(attemptNumber));
    setParams(next, { replace: true });
  }
  function change(name: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  }
  if (run.error) return <Notice>{run.error.message}</Notice>;
  if (!data) return <Loading what="run" />;
  if (!addressed) return <Notice>Run #{id} belongs to {data.pipeline_code}.</Notice>;

  const byTask = new Map(status.data?.tasks.map((item) => [item.task_code, item.explanation.task]));
  const byStep = new Map(steps.data?.steps.map((step) => [step.task_code, step]));
  const graph = status.data ? runGraph(status.data) : null;
  const waves = graph?.waves.flat() ?? [];
  const alerts = waves.filter((name) => byStep.get(name)?.handler === "ALERT" && !graph?.depends_on[name]?.length);
  const order = [...waves.filter((name) => !alerts.includes(name)), ...alerts.sort()];
  const statuses = Object.fromEntries(status.data?.tasks.map((item) => [item.task_code, taskStatus(item.status, data)]) ?? []);
  const failures = [...byTask.values()].filter((item): item is TaskRunView => item != null && isFailure(item.status));
  const tolerated = data.status === "SUCCESS";
  const failureTitle = tolerated ? "Tolerated failures" : "Failed tasks";
  const optional = steps.data?.steps.filter(step => step.parameters?.FAIL_PIPELINE_IF_FAILED?.toUpperCase() === "N").map(step => step.task_code);
  const blocked = blockedTasks(status.data, order);
  const error = steps.error ?? status.error;
  return <div className="grid min-w-0 content-start gap-4">
    <Breadcrumbs separator="›" trail={[{ label: pipeline, to: pipelineRunPath(code, pipeline, data.pipeline_run_id) }, { label: `Run #${id}` }]} />
    <PageHeader compact title={<span title={data.run_label}>Run #{id}</span>}
      status={<>
        <StatusBadge status={data.status} />
        {data.selected_task_ids?.length && order.length ? <span className="text-sm">{data.selected_task_ids.length} of {order.length} tasks</span> : null}
      </>}
      actions={<div className="flex flex-wrap gap-2">
        <RunRecovery code={code} run={data} task={task} tasks={order} onDone={() => void run.refetch()} />
        {live(data) ? <CancelRun code={code} run={data} onDone={() => void run.refetch()} /> : null}
        <Button onClick={() => void navigator.clipboard.writeText(data.run_label ? copyRunLabel(data.run_label) : String(id))
          .then(() => toast("Run identifier copied."), () => toast("Could not copy the run identifier."))}>Copy id</Button>
      </div>}>
      <RunFacts run={data} />
    </PageHeader>
    {failures.length ? <section aria-label={failureTitle} className={`grid gap-2 rounded-md border p-3 ${tolerated ? "border-warn bg-warn-bg" : "border-bad bg-surface"}`}>
      <h2 className={`text-sm font-semibold ${tolerated ? "text-warn" : "text-bad"}`}>{failureTitle}</h2>
      <ul className="grid gap-2">
        {failures.map((item) => {
          const failed = item.attempts.findLast((attempt) => isFailure(attempt.status));
          return <li key={item.task_code} className="flex flex-wrap items-center gap-2 text-sm">
            <strong>{item.task_code}</strong>
            {failed ? <span>Try {failed.attempt_number} of {item.attempt_count}</span> : null}
            <span className="min-w-0 break-words">{(failed?.error_message ?? item.error_message)?.split("\n")[0]}</span>
            <Button size="sm" onClick={() => selectTask(item.task_code, true, failed === item.attempts.at(-1) ? undefined : failed?.attempt_number)} aria-label={`Show task ${item.task_code}`}>Show task</Button>
          </li>;
        })}
      </ul>
    </section> : null}
    <div className={task ? "grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,37%)]" : "grid min-w-0 gap-4"}>
      <section className="grid min-w-0 content-start gap-3">
        <Tabs tabs={views} value={view} onChange={(value) => change("view", value)} panelId="run-view" />
        <div id="run-view" role="tabpanel" aria-labelledby={`tab-${view}`} className="grid min-w-0 gap-3">
          {error ? <Notice>{error.message}</Notice> : null}
          {view !== "events" && !error && (!graph || !steps.data) ? <Loading what="run tasks" /> : null}
          {view === "graph" && graph ? <RunGraph graph={graph} statuses={statuses} blocked={blocked} optional={optional} focused={task} onFocus={selectTask} onOpen={selectTask} /> : null}
          {view === "list" && graph && status.data && steps.data ? <TaskList rows={order.map((name) => ({
            name, status: statuses[name] ?? "NOT_STARTED", handler: byStep.get(name)?.handler,
            task: byTask.get(name), condition: byStep.get(name)?.run_condition || "Pipeline is admitted",
            optional: optional?.includes(name) ?? false,
          }))} select={selectTask} selected={task} /> : null}
          {view === "gantt" ? <>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={critical} onChange={(event) => setCritical(event.target.checked)} /> Critical path</label>
            <RunTimeline run={data} order={order} selected={task} onTask={selectTask} critical={critical && graph ? criticalPath(graph, byTask) : undefined} />
          </> : null}
          {view === "events" ? <RunEvents code={code} run={data} /> : null}
        </div>
      </section>
      {task ? <aside className="grid min-w-0 content-start gap-2 rounded-md border border-border bg-surface p-3 max-lg:order-first">
        <Button className="justify-self-end" size="sm" onClick={() => selectTask(null)}>Close task</Button>
        <TaskDetails key={`${id}:${task}`} code={code} pipeline={pipeline} run={data} task={task} handler={byStep.get(task)?.handler}
          tab={params.get("taskTab") ?? "logs"} tryNumber={params.has("try") ? Number(params.get("try")) : null}
          firstError={params.has("error")} onTab={(value) => change("taskTab", value)} onTry={(value) => change("try", value === null ? null : String(value))} />
      </aside> : null}
    </div>
  </div>;
}

function runGraph(status: RunStatusView): Graph {
  const names = status.tasks.map((task) => task.task_code);
  const local = new Set(names);
  const dependencies: Graph["depends_on"] = Object.fromEntries(status.tasks.map((task) => [
    task.task_code, task.explanation.dependencies.map((edge) => [edge.upstream, edge.dependency_type]),
  ]));
  const internal = Object.fromEntries(Object.entries(dependencies).map(([name, edges]) => [
    name, edges.filter(([upstream]) => local.has(upstream)),
  ]));
  return {
    waves: dependencyWaves(names, internal),
    conditional: status.tasks.filter((task) => Boolean(task.explanation.run_condition)).map((task) => task.task_code),
    depends_on: dependencies,
  };
}

function blockedTasks(status: RunStatusView | undefined, order: string[]): string[] {
  if (!status) return [];
  const byTask = new Map(status.tasks.map((task) => [task.task_code, task]));
  const blocked = new Set(status.blocked_by_failures);
  for (const name of order) {
    const row = byTask.get(name);
    if (row?.status !== "SKIPPED" || row.explanation.task?.attempt_count) continue;
    const { dependencies, condition_met } = row.explanation;
    if (condition_met === true) continue;
    if (dependencies.some((edge) => !edge.met && (isFailure(edge.status) || blocked.has(edge.upstream)))) {
      blocked.add(name);
    }
  }
  return [...blocked];
}

type TaskRow = { name: string; status: string; handler?: string; task?: TaskRunView | null; condition: string; optional: boolean };

function TaskList({ rows, select, selected }: { rows: TaskRow[]; select: (task: string) => void; selected: string | null }) {
  const [filter, setFilter] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const now = useNow();
  const duration = (row: TaskRow) => row.task?.start_date
    ? (row.task.end_date ? Date.parse(row.task.end_date) : now) - Date.parse(row.task.start_date) : null;
  return <>
    <div className="flex flex-wrap items-center gap-2">
      <input type="search" aria-label="Search tasks by name" name="search-tasks" autoComplete="off" placeholder="Search tasks…" value={search} onChange={(event) => setSearch(event.target.value)} className="h-control rounded-md border border-border-strong bg-surface px-2 text-sm" />
      <ChecklistFilter label="Task status" noun="statuses" one="status" known={[...new Set(rows.map((row) => row.status))]} selected={filter} onChange={setFilter} name={(value) => statusMeta(value).label} />
    </div>
    <DataTable label="Run tasks" data={rows.filter((row) => row.name.toLowerCase().includes(search.trim().toLowerCase()) && (!filter.length || filter.includes(row.status)))}
      highlight={(row) => row.name === selected} columns={columnsOf<TaskRow>([
        { id: "task", header: "Task", value: (row) => row.name, cell: (row) => <><button type="button" className="text-left text-accent hover:underline" onClick={() => select(row.name)}>{row.name}</button>{row.optional ? <> <OptionalTask /></> : null}</> },
        { id: "status", header: "Status", value: (row) => row.status, cell: (row) => <StatusBadge quiet status={row.status} /> },
        { id: "handler", header: "Handler", value: (row) => row.handler ? handlerLabel(row.handler) : null },
        { id: "try", header: "Try", value: (row) => row.task?.attempt_count ?? null },
        { id: "start", header: "Started", value: (row) => row.task?.start_date ?? null, cell: (row) => <When iso={row.task?.start_date} /> },
        { id: "duration", header: "Duration", value: duration, cell: (row) => formatDuration(row.task?.start_date ?? null, row.task?.end_date ?? null, now) },
        { id: "in", header: "Rows in", value: (row) => row.task?.source_count ?? null },
        { id: "written", header: "Rows written", value: (row) => row.task?.rows_written ?? null },
        { id: "rejected", header: "Rows rejected", value: (row) => row.task?.reject_count ?? null },
        { id: "condition", header: "Runs when", value: (row) => row.condition },
      ])} />
  </>;
}

function criticalPath(graph: Graph, tasks: Map<string, TaskRunView | null>) {
  const paths = new Map<string, { duration: number; tasks: string[] }>();
  for (const name of graph.waves.flat()) {
    const task = tasks.get(name);
    if (!task?.start_date || !task.end_date) continue;
    const upstream = (graph.depends_on[name] ?? []).map(([key]) => paths.get(key))
      .reduce<{ duration: number; tasks: string[] }>((best, path) => path && path.duration > best.duration ? path : best, { duration: 0, tasks: [] });
    paths.set(name, { duration: upstream.duration + Date.parse(task.end_date) - Date.parse(task.start_date), tasks: [...upstream.tasks, name] });
  }
  return new Set([...paths.values()].sort((a, b) => b.duration - a.duration)[0]?.tasks);
}

function CancelRun({ code, run, onDone }: { code: string; run: RunView; onDone: () => void }) {
  const caps = useQuery({
    queryKey: ["capabilities", code, run.pipeline_code, run.pipeline_run_id, run.status],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
  });
  const stop = controlAnswers(caps.data, caps.error).find((answer) => answer.action === "STOP");
  return <ActionButton<ControlView> code={code} label="Cancel" title={`Cancel run #${run.pipeline_run_id}`}
    unavailableReason={stop?.available ? undefined : stop?.reason ?? "Checking whether the run can be cancelled."}
    endpoint="/controls" effect="Requests a stop for this run and its active attempts."
    body={(reason) => ({ pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, action: "STOP", reason })}
    describe={(result) => result.message} onDone={onDone} />;
}

function RunEvents({ code, run }: { code: string; run: RunView }) {
  const [task, setTask] = useState("");
  const [kind, setKind] = useState("");
  const log = useQuery({
    queryKey: ["run-events", code, run.pipeline_run_id, run.end_date],
    queryFn: () => getText(`${project(code)}/run-log`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
    refetchInterval: live(run),
  });
  if (log.error) return <Notice>{log.error.message}</Notice>;
  if (log.isPending) return <Loading what="run events" />;
  const events = log.data.split("\n").flatMap((line) => {
    const match = /^(\S+)\s+(\w+)\s+run=\d+ task=(\S+) actor=(.*)$/.exec(line);
    if (!match) return [];
    const [, at, code, task, details] = match;
    const kind = eventLabels[code!];
    if (!kind) return [];
    return [{ at: at!, kind, task: task!, details: details!.replace(/^-(?: |$)/, "") }];
  });
  const options = (values: string[]) => [...new Set(values)].sort();
  const names = options(events.map((event) => event.task)).filter((name) => name !== "-");
  const kinds = options(events.map((event) => event.kind));
  return <>
    <div className="flex flex-wrap items-center gap-3">
      <SelectField compact label="Task" value={task} onChange={setTask}><option value="">All tasks</option>{names.map((name) => <option key={name}>{name}</option>)}</SelectField>
      <SelectField compact label="Kind" value={kind} onChange={setKind}><option value="">All kinds</option>{kinds.map((name) => <option key={name} value={name}>{name}</option>)}</SelectField>
    </div>
    <ol aria-label="Run events" className="grid gap-2 text-sm">
      {events.filter((event) => (!task || event.task === task) && (!kind || event.kind === kind)).map((event, index) => <li key={index} className="grid gap-1 rounded-md border border-border p-2">
        <span><When iso={event.at} /> · {event.kind}{event.task === "-" ? "" : ` · ${event.task}`}</span>
        {event.details ? <span className="break-words text-muted">{event.details}</span> : null}
      </li>)}
    </ol>
  </>;
}
