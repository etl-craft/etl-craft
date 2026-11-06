import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Copy, Download, LifeBuoy } from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Fact, FactList, Loading, Notice, PageHeader } from "@/components/common";
import { ActionButton } from "@/components/action-button";
import { AttemptDetails } from "@/components/attempt-details";
import { useToast } from "@/components/toast";
import { ScopeControls } from "@/components/scope-controls";
import { RunGraph } from "@/components/run-graph";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { useCanRun, useProjectInfo, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { attemptPath, itemsPath, runsPath, taskPath } from "@/lib/routes";
import type { Capabilities, ControlView, Explanation, Graph, RunView, Steps, TaskHistory } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const RECOVERABLE = new Set(["FAILED", "LOST", "STOPPED", "ABORTED"]);

function Why({ code, pipeline, runId, task }: { code: string; pipeline: string; runId: number; task: string }) {
  const why = useQuery({
    queryKey: ["explain", code, pipeline, runId, task],
    queryFn: () => getJson<Explanation>(`${project(code)}/explanations`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  if (!why.data) return why.isError ? <Notice>{(why.error as Error).message}</Notice> : null;
  const { dependencies, run_condition: condition, required_count: required, retry_at: retry } = why.data;
  return (
    <section className="grid gap-2" aria-label="Why this task is in this state">
      <h3 className="m-0 text-sm font-semibold">Dependencies</h3>
      <p className="m-0 text-[13px] text-muted">
        Runs when {condition.toLowerCase()}
        {required ? ` (${required} required)` : ""}.{retry ? ` Retry at ${retry}.` : ""}
      </p>
      <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
        {dependencies.map((d) => (
          <li key={d.upstream} className="flex flex-wrap items-center gap-2">
            {d.status ? <StatusBadge status={d.status} /> : <span className="text-muted">Not started</span>}
            <span className="font-medium">{d.upstream}</span>
            <span className="text-muted">{d.met ? "met" : "not met"}: {d.reason}</span>
          </li>
        ))}
        {dependencies.length === 0 ? <li className="text-muted">No upstream tasks.</li> : null}
      </ul>
    </section>
  );
}

function TaskPanel({ code, pipeline, runId, task, handler }: { code: string; pipeline: string; runId: number; task: string; handler?: string }) {
  const history = useQuery({
    queryKey: ["task-history", code, pipeline, runId, task],
    queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  const run = history.data?.entries[0];
  return (
    <Card aria-label={`Task ${task}`}>
      <CardHeader>
        <CardTitle>{task}</CardTitle>
        <span className="flex items-center gap-3">
          <Link to={taskPath(code, pipeline, task)} className="text-xs text-accent hover:underline">
            Task history
          </Link>
          {handler === "PYTHON" ? (
            <Link to={itemsPath(code, pipeline, runId, task)} className="text-xs text-accent hover:underline">
              Items
            </Link>
          ) : null}
          {run ? <StatusBadge status={run.status} /> : null}
        </span>
      </CardHeader>
      <div className="grid gap-4 p-4">
        {history.isPending ? <Loading what="task" /> : null}
        {history.isError ? <Notice>{(history.error as Error).message}</Notice> : null}
        {history.isSuccess && !run ? <p className="m-0 text-muted">This task has not started under this run.</p> : null}
        {run?.error_message ? <Notice mono>{run.error_message}</Notice> : null}
        <ScopeControls code={code} pipeline={pipeline} runId={runId} task={task} />
        {run && run.status !== "SUCCESS" ? <Why code={code} pipeline={pipeline} runId={runId} task={task} /> : null}
        {run && run.attempts.length === 0 ? (
          <p className="m-0 text-muted">No attempt was started for this task{run.status === "SKIPPED" ? ": an upstream outcome skipped it" : ""}.</p>
        ) : null}
        {run?.attempts.map((attempt) => (
          <div key={attempt.attempt_id} className="grid gap-2 rounded-md border border-border p-3">
            <AttemptDetails code={code} attempt={attempt} />
            <Link to={attemptPath(code, pipeline, runId, task, attempt.attempt_id)} className="w-fit text-xs text-accent hover:underline">
              Open attempt {attempt.attempt_number}
            </Link>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** The run's own log and every attempt's log, downloaded as the API streams them; and, while it runs, fencing of expired owners. */
function RunTools({ code, run, canRun }: { code: string; run: RunView; canRun: boolean }) {
  const query = `pipeline_code=${encodeURIComponent(run.pipeline_code)}&run_id=${run.pipeline_run_id}`;
  const file = (path: string, name: string, label: string) => (
    <Button asChild size="sm">
      <a href={`${project(code)}${path}?${query}`} download={name}>
        <Download className="size-4" aria-hidden /> {label}
      </a>
    </Button>
  );
  const toast = useToast();
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        size="sm"
        onClick={() => {
          void navigator.clipboard.writeText(run.run_key).then(() => toast("Run key copied."));
        }}
      >
        <Copy className="size-4" aria-hidden /> Copy run key
      </Button>
      {file("/run-log", `run-${run.pipeline_run_id}.log`, "Download run log")}
      {file("/run-zip", `run-${run.pipeline_run_id}-logs.zip`, "Download logs (zip)")}
      {canRun && !run.end_date ? (
        <ActionButton<{ message: string }>
          code={code}
          label="Reconcile"
          title={`Reconcile ${run.pipeline_code} run #${run.pipeline_run_id}`}
          effect="Fences attempts whose owner stopped renewing their lease and records them as LOST, so their tasks can be retried; live attempts are untouched."
          endpoint="/reconciliations"
          body={(reason) => ({ pipeline_code: run.pipeline_code, reason })}
          describe={(r) => r.message}
          size="sm"
        />
      ) : null}
    </div>
  );
}

function RecoverRun({ code, run, canRun }: { code: string; run: RunView; canRun: boolean }) {
  const caps = useQuery({
    queryKey: ["capabilities", code, run.pipeline_code, run.pipeline_run_id, run.status],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
    enabled: canRun,
  });
  const capability = caps.data?.actions.find((a) => a.action === "RECOVER");
  if (!canRun || !capability || (!capability.available && !RECOVERABLE.has(run.status))) return null;
  return (
    <div className="grid justify-items-end gap-2">
      {capability.available ? (
        <ActionButton<ControlView>
          code={code}
          label="Recover run"
          title={`Recover run #${run.pipeline_run_id}`}
          effect={`Reopens ${run.pipeline_code} run #${run.pipeline_run_id}: tasks that succeeded are kept; failed and unfinished tasks run again.`}
          endpoint="/controls"
          body={(reason) => ({ pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, action: "RECOVER", reason })}
          describe={(r) => `Recover accepted: control #${r.control_id}${r.execution_run_id ? `, execution #${r.execution_run_id}` : ""}. ${r.message}`}
          icon={<LifeBuoy className="size-4" aria-hidden />}
          variant="primary"
        />
      ) : (
        <Button variant="primary" disabled title="Not available now; the reason is listed under Controls">
          <LifeBuoy className="size-4" aria-hidden /> Recover run
        </Button>
      )}
    </div>
  );
}

export function RunDetail() {
  const { project: code = "", pipeline = "", runId = "" } = useParams();
  const id = Number(runId);
  const tz = useTimezone();
  const info = useProjectInfo(code);
  const [focused, setFocused] = React.useState<string | null>(null);
  const [opened, setOpened] = React.useState<string | null>(null);
  const panel = React.useRef<HTMLDivElement>(null);
  const open = (task: string) => {
    setFocused(task);
    setOpened(task);
  };
  React.useEffect(() => {
    if (opened) panel.current?.scrollIntoView({ block: "nearest" });
  }, [opened]);
  const live = (status?: string) => (status === "IN-PROGRESS" ? 5_000 : false);

  const run = useQuery({
    queryKey: ["run", code, id],
    queryFn: () => getJson<RunView>(`${project(code)}/runs/${id}`),
    refetchInterval: (query) => live(query.state.data?.status),
  });
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, id],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: id }),
    refetchInterval: () => live(run.data?.status),
  });
  const graph = useQuery({ queryKey: ["graph", code, pipeline], queryFn: () => getJson<Graph>(`${project(code)}/graph`, { pipeline_code: pipeline }) });

  useDocumentTitle(`${pipeline} #${runId}`, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const statuses = Object.fromEntries((steps.data?.steps ?? []).map((s) => [s.task_code, s.status ?? "QUEUED"]));
  const order = new Map((graph.data?.waves ?? []).flat().map((task, index) => [task, index]));
  const ordered = [...(steps.data?.steps ?? [])].sort((a, b) => (order.get(a.task_code) ?? 0) - (order.get(b.task_code) ?? 0));
  const canRun = useCanRun(code);

  if (run.isError) {
    return (
      <Notice>{(run.error as Error).message}</Notice>
    );
  }
  const r = run.data;
  return (
    <div className="grid grid-cols-1 gap-5">
      <Link to={runsPath(code, pipeline)} className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> {pipeline} runs
      </Link>
      <PageHeader
        title={
          <>
            {pipeline} <span className="num text-muted">#{runId}</span>
          </>
        }
        status={r ? <StatusBadge status={r.status} /> : null}
        actions={r ? <RecoverRun code={code} run={r} canRun={canRun} /> : null}
      >
        {r ? (
          <FactList>
            <Fact label="Started">{formatTime(r.start_date, tz)}</Fact>
            <Fact label="Ended">{formatTime(r.end_date, tz)}</Fact>
            <Fact label="Duration">{formatDuration(r.start_date, r.end_date)}</Fact>
            <Fact label="Logical date">{r.run_date ?? "—"}</Fact>
            <Fact label="Trigger">{r.trigger_kind.toLowerCase()}</Fact>
            <Fact label="Started by">{r.started_by ?? "—"}</Fact>
            <Fact label="Run key">
              <span className="break-all">{r.run_key}</span>
            </Fact>
            {r.sla_status ? <Fact label="SLA">{r.sla_status}</Fact> : null}
          </FactList>
        ) : (
          <Loading what="run" />
        )}
      </PageHeader>
      {r ? <RunTools code={code} run={r} canRun={canRun} /> : null}
      <ScopeControls code={code} pipeline={pipeline} runId={id} elsewhere={["RECOVER"]} />
      <Card>
        <CardHeader>
          <CardTitle>Tasks</CardTitle>
          <span className="text-xs text-muted">Click a task for its lineage; use its arrow for status, attempts and log</span>
        </CardHeader>
        {graph.isSuccess ? <RunGraph graph={graph.data} statuses={statuses} focused={focused} onFocus={setFocused} onOpen={open} /> : graph.isError ? <Notice className="m-4">{(graph.error as Error).message}</Notice> : <Loading what="graph" className="p-4" />}
      </Card>
      <Card>
        <Table aria-label="Task list">
          <thead>
            <tr>
              <Th>Task</Th>
              <Th>Status</Th>
              <Th>Handler</Th>
              <Th>Runs when</Th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((step) => (
              <tr key={step.task_code} className={step.task_code === opened ? "bg-surface-2" : "hover:bg-surface-2"}>
                <Td>
                  <button type="button" className="cursor-pointer font-medium text-accent hover:underline" aria-pressed={step.task_code === opened} onClick={() => open(step.task_code)}>
                    {step.task_code}
                  </button>
                </Td>
                <Td>
                  <StatusBadge status={step.status ?? "QUEUED"} />
                </Td>
                <Td>{step.handler}</Td>
                <Td className="text-muted">{step.run_condition ? step.run_condition.toLowerCase() : "all upstream succeed"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {opened ? (
        <div ref={panel}>
          <TaskPanel code={code} pipeline={pipeline} runId={id} task={opened} handler={steps.data?.steps.find((x) => x.task_code === opened)?.handler} />
        </div>
      ) : null}
    </div>
  );
}
