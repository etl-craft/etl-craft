import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, LifeBuoy } from "lucide-react";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { RunGraph } from "@/components/run-graph";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { useIdentity, useProjectInfo, useTimezone } from "@/hooks";
import { ApiError, getJson, getText, postJson, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import type { Capabilities, ControlView, Graph, RunView, Steps, TaskHistory } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const RECOVERABLE = new Set(["FAILED", "LOST", "STOPPED", "ABORTED"]);

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="num m-0">{children}</dd>
    </div>
  );
}

function AttemptLog({ code, attemptId }: { code: string; attemptId: number }) {
  const [shown, setShown] = React.useState(false);
  const log = useQuery({ queryKey: ["log", code, attemptId], queryFn: () => getText(`${project(code)}/attempts/${attemptId}/log`), enabled: shown });
  const lines = log.data?.split("\n") ?? [];
  return (
    <div className="grid gap-2">
      <Button size="sm" className="w-fit" onClick={() => setShown(!shown)} aria-expanded={shown}>
        {shown ? "Hide log" : "Show log"}
      </Button>
      {shown && log.isPending ? <p className="text-muted">Loading log…</p> : null}
      {shown && log.isError ? (
        <p role="alert" className="rounded-md bg-bad-bg p-3 text-sm text-bad">
          {(log.error as Error).message}
        </p>
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
        {history.isPending ? <p className="text-muted">Loading task…</p> : null}
        {history.isError ? (
          <p role="alert" className="rounded-md bg-bad-bg p-3 text-sm text-bad">
            {(history.error as Error).message}
          </p>
        ) : null}
        {history.isSuccess && !run ? <p className="text-muted">This task has not started under this run.</p> : null}
        {run?.error_message ? (
          <p role="alert" className="m-0 whitespace-pre-wrap rounded-md bg-bad-bg p-3 font-mono text-xs text-bad">
            {run.error_message}
          </p>
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
            <dl className="m-0 grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
              <Fact label="Started">{formatTime(attempt.started_at, tz)}</Fact>
              <Fact label="Duration">{formatDuration(attempt.started_at, attempt.ended_at)}</Fact>
              <Fact label="Rows written">{attempt.rows_written ?? "—"}</Fact>
              <Fact label="Exit code">{attempt.exit_code ?? "—"}</Fact>
              <Fact label="Host">
                <span className="break-all">{attempt.host ?? "—"}</span>
              </Fact>
              <Fact label="Failure class">{attempt.status === "FAILED" ? attempt.failure_class : "—"}</Fact>
              <Fact label="Retry on">{attempt.retry_on ?? "—"}</Fact>
            </dl>
            <AttemptLog code={code} attemptId={attempt.attempt_id} />
          </section>
        ))}
      </div>
    </Card>
  );
}

function RecoverRun({ code, run, canRun }: { code: string; run: RunView; canRun: boolean }) {
  const info = useProjectInfo(code);
  const client = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const caps = useQuery({
    queryKey: ["capabilities", code, run.pipeline_code, run.pipeline_run_id, run.status],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
    enabled: canRun,
  });
  const recover = useMutation({
    mutationFn: (reason: string) =>
      postJson<ControlView>(`${project(code)}/controls`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, action: "RECOVER", reason }),
    onSuccess: () => void client.invalidateQueries(),
  });
  const capability = caps.data?.actions.find((a) => a.action === "RECOVER");
  if (!canRun || !info.project || !capability || (!capability.available && !RECOVERABLE.has(run.status))) return null;
  const env = { type: info.project.environment_type, name: info.project.environment_name };
  const result = recover.data;
  return (
    <div className="grid justify-items-end gap-2">
      <Button
        variant="primary"
        disabled={!capability.available}
        onClick={() => {
          recover.reset();
          setOpen(true);
        }}
      >
        <LifeBuoy className="size-4" aria-hidden /> Recover run
      </Button>
      {!capability.available ? <p className="m-0 max-w-md text-right text-xs text-muted">{capability.reason}</p> : null}
      {result ? (
        <p role="status" className="m-0 max-w-md text-right text-xs">
          Recover accepted: control #{result.control_id}
          {result.execution_run_id ? `, execution #${result.execution_run_id}` : ""}. {result.message}
        </p>
      ) : null}
      <ConfirmDialog
        open={open && !result}
        title={`Recover run #${run.pipeline_run_id}`}
        action="Recover run"
        effect={`Reopens ${run.pipeline_code} run #${run.pipeline_run_id}: tasks that succeeded are kept; failed and unfinished tasks run again.`}
        projectCode={code}
        env={env}
        error={recover.error instanceof ApiError ? recover.error.message : recover.error ? "The request did not complete." : null}
        busy={recover.isPending}
        onConfirm={(reason) => recover.mutate(reason)}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

export function RunDetail() {
  const { project: code = "", pipeline = "", runId = "" } = useParams();
  const id = Number(runId);
  const tz = useTimezone();
  const identity = useIdentity(code);
  const info = useProjectInfo(code);
  const [selected, setSelected] = React.useState<string | null>(null);
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
  const permission = identity.data?.project_permission;
  const canRun = identity.data?.role === "admin" || permission === "CAN_RUN" || permission === "CAN_MANAGE";
  const first = ordered.find((s) => s.status === "FAILED")?.task_code ?? null;
  const open = selected ?? first;

  if (run.isError) {
    return (
      <p role="alert" className="rounded-md bg-bad-bg p-3 text-sm text-bad">
        {(run.error as Error).message}
      </p>
    );
  }
  const r = run.data;
  return (
    <div className="grid grid-cols-1 gap-5">
      <Link to={`/projects/${encodeURIComponent(code)}/runs?pipeline=${encodeURIComponent(pipeline)}`} className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> {pipeline} runs
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="m-0 text-2xl font-semibold">
              {pipeline} <span className="num text-muted">#{runId}</span>
            </h1>
            {r ? <StatusBadge status={r.status} /> : null}
          </div>
          {r ? (
            <dl className="m-0 grid grid-cols-2 gap-x-8 gap-y-3 text-[13px] sm:grid-cols-3 lg:grid-cols-5">
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
            </dl>
          ) : (
            <p className="text-muted">Loading run…</p>
          )}
        </div>
        {r ? <RecoverRun code={code} run={r} canRun={canRun} /> : null}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Tasks</CardTitle>
          <span className="text-xs text-muted">Select a task for its attempts and log</span>
        </CardHeader>
        {graph.isSuccess ? <RunGraph graph={graph.data} statuses={statuses} selected={open} onSelect={setSelected} /> : <p className="p-4 text-muted">{graph.isError ? (graph.error as Error).message : "Loading graph…"}</p>}
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
              <tr key={step.task_code} className={step.task_code === open ? "bg-surface-2" : "hover:bg-surface-2"}>
                <Td>
                  <button type="button" className="cursor-pointer font-medium text-accent hover:underline" aria-pressed={step.task_code === open} onClick={() => setSelected(step.task_code)}>
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
      {open ? <TaskPanel code={code} pipeline={pipeline} runId={id} task={open} /> : null}
    </div>
  );
}
