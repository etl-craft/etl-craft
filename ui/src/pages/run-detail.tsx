import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, LifeBuoy } from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Fact, FactList, Loading, Notice, PageHeader } from "@/components/common";
import { ActionButton } from "@/components/action-button";
import { RunGraph } from "@/components/run-graph";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { useCanRun, useProjectInfo, useTimezone } from "@/hooks";
import { getJson, getText, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { runsPath } from "@/lib/routes";
import type { Capabilities, ControlView, Graph, RunView, Steps, TaskHistory } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const RECOVERABLE = new Set(["FAILED", "LOST", "STOPPED", "ABORTED"]);

function AttemptLog({ code, attemptId }: { code: string; attemptId: number }) {
  const [shown, setShown] = React.useState(false);
  const log = useQuery({ queryKey: ["log", code, attemptId], queryFn: () => getText(`${project(code)}/attempts/${attemptId}/log`), enabled: shown });
  const lines = log.data?.split("\n") ?? [];
  return (
    <div className="grid gap-2">
      <Button size="sm" className="w-fit" onClick={() => setShown(!shown)} aria-expanded={shown}>
        {shown ? "Hide log" : "Show log"}
      </Button>
      {shown && log.isPending ? <Loading what="log" /> : null}
      {shown && log.isError ? (
        <Notice>{(log.error as Error).message}</Notice>
      ) : null}
      {shown && log.isSuccess ? (
        <>
          {lines.length > 400 ? <p className="text-xs text-muted">Showing the last 400 of {lines.length} lines.</p> : null}
          <pre tabIndex={0} aria-label="Attempt log" className="m-0 max-h-96 overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs leading-5">
            {lines.slice(-400).join("\n")}
          </pre>
        </>
      ) : null}
    </div>
  );
}

function TaskPanel({ code, pipeline, runId, task }: { code: string; pipeline: string; runId: number; task: string }) {
  const tz = useTimezone();
  const history = useQuery({
    queryKey: ["task-history", code, pipeline, runId, task],
    queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  const run = history.data?.entries[0];
  return (
    <Card aria-label={`Task ${task}`}>
      <CardHeader>
        <CardTitle>{task}</CardTitle>
        {run ? <StatusBadge status={run.status} /> : null}
      </CardHeader>
      <div className="grid gap-4 p-4">
        {history.isPending ? <Loading what="task" /> : null}
        {history.isError ? (
          <Notice>{(history.error as Error).message}</Notice>
        ) : null}
        {history.isSuccess && !run ? <p className="text-muted">This task has not started under this run.</p> : null}
        {run?.error_message ? (
          <Notice mono>{run.error_message}</Notice>
        ) : null}
        {run && run.attempts.length === 0 ? (
          <p className="m-0 text-muted">No attempt was started for this task{run.status === "SKIPPED" ? ": an upstream outcome skipped it" : ""}.</p>
        ) : null}
        {run?.attempts.map((attempt) => (
          <section key={attempt.attempt_id} className="grid gap-3 rounded-md border border-border p-3" aria-label={`Attempt ${attempt.attempt_number}`}>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="m-0 text-sm font-semibold">Attempt {attempt.attempt_number}</h3>
              <StatusBadge status={attempt.status} />
              <span className="num text-xs text-muted">id {attempt.attempt_id}</span>
            </div>
            <FactList className="gap-3 sm:grid-cols-4 lg:grid-cols-4">
              <Fact label="Started">{formatTime(attempt.started_at, tz)}</Fact>
              <Fact label="Duration">{formatDuration(attempt.started_at, attempt.ended_at)}</Fact>
              <Fact label="Rows written">{attempt.rows_written ?? "—"}</Fact>
              <Fact label="Exit code">{attempt.exit_code ?? "—"}</Fact>
              <Fact label="Host">
                <span className="break-all">{attempt.host ?? "—"}</span>
              </Fact>
              <Fact label="Failure class">{attempt.status === "FAILED" ? attempt.failure_class : "—"}</Fact>
              <Fact label="Retry on">{attempt.retry_on ?? "—"}</Fact>
            </FactList>
            <AttemptLog code={code} attemptId={attempt.attempt_id} />
          </section>
        ))}
      </div>
    </Card>
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
        <>
          <Button variant="primary" disabled>
            <LifeBuoy className="size-4" aria-hidden /> Recover run
          </Button>
          <p className="m-0 max-w-md text-right text-xs text-muted">{capability.reason}</p>
        </>
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
          <TaskPanel code={code} pipeline={pipeline} runId={id} task={opened} />
        </div>
      ) : null}
    </div>
  );
}
