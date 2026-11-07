import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Copy, Download, LifeBuoy } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { Fact, FactList, Loading, Notice } from "@/components/common";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "@/components/dropdown";
import { ActionButton } from "@/components/action-button";
import { AttemptDetails } from "@/components/attempt-details";
import { useToast } from "@/components/toast";
import { ScopeControls } from "@/components/scope-controls";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Table, Td, Th } from "@/components/ui/table";
import { useCanRun, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { attemptPath, itemsPath, taskPath } from "@/lib/routes";
import type { Capabilities, ControlView, Explanation, Graph, RunView, Steps, TaskHistory } from "@/lib/types";

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

/** What a task row opens in place: its state, controls, why it waits, and each attempt with its evidence and log. */
function TaskDetails({ code, pipeline, runId, task, handler }: { code: string; pipeline: string; runId: number; task: string; handler?: string }) {
  const history = useQuery({
    queryKey: ["task-history", code, pipeline, runId, task],
    queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  const run = history.data?.entries[0];
  return (
    <section aria-label={`Task ${task}`} className="grid gap-3 border-l-2 border-accent bg-surface-2 p-4">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <Link to={taskPath(code, pipeline, task)} className="text-accent hover:underline">
          Task history
        </Link>
        {handler === "PYTHON" ? (
          <Link to={itemsPath(code, pipeline, runId, task)} className="text-accent hover:underline">
            Items
          </Link>
        ) : null}
      </div>
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
        <div key={attempt.attempt_id} className="grid gap-2 rounded-md border border-border bg-surface p-3">
          <AttemptDetails code={code} attempt={attempt} />
          <Link to={attemptPath(code, pipeline, runId, task, attempt.attempt_id)} className="w-fit text-xs text-accent hover:underline">
            Open attempt {attempt.attempt_number}
          </Link>
        </div>
      ))}
    </section>
  );
}

/** The run's key and logs, as the API streams them, and, while it runs, fencing of expired owners: one menu, not a row of buttons. */
function RunTools({ code, run, canRun }: { code: string; run: RunView; canRun: boolean }) {
  const query = `pipeline_code=${encodeURIComponent(run.pipeline_code)}&run_id=${run.pipeline_run_id}`;
  const toast = useToast();
  const file = (path: string, name: string, label: string) => (
    <DropdownItem asChild>
      <a href={`${project(code)}${path}?${query}`} download={name}>
        <Download className="size-4" aria-hidden /> {label}
      </a>
    </DropdownItem>
  );
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DropdownMenu>
        <DropdownTrigger asChild>
          <Button size="sm" variant="outline" aria-label="Run key and logs">
            Logs and key
            <ChevronDown className="size-3.5" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent align="end">
          <DropdownItem onSelect={() => void navigator.clipboard.writeText(run.run_key).then(() => toast("Run key copied."))}>
            <Copy className="size-4" aria-hidden /> Copy run key
          </DropdownItem>
          {file("/run-log", `run-${run.pipeline_run_id}.log`, "Download run log")}
          {file("/run-zip", `run-${run.pipeline_run_id}-logs.zip`, "Download logs (zip)")}
        </DropdownContent>
      </DropdownMenu>
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

/**
 * The selected run: its state, identifier, times and controls, and one task table whose rows open in place
 * to the task's attempts, evidence and log. The task open is the address's, so a grid cell can open it.
 */
export function RunOverview({ code, pipeline, runId, task, onTask }: { code: string; pipeline: string; runId: number; task: string | null; onTask: (task: string | null) => void }) {
  const tz = useTimezone();
  const toast = useToast();
  const canRun = useCanRun(code);
  const panel = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (task) panel.current?.scrollIntoView({ block: "nearest" });
  }, [task]);
  const live = (status?: string) => (status === "IN-PROGRESS" ? 5_000 : false);
  const run = useQuery({
    queryKey: ["run", code, runId],
    queryFn: () => getJson<RunView>(`${project(code)}/runs/${runId}`),
    refetchInterval: (query) => live(query.state.data?.status),
  });
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, runId],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: runId }),
    refetchInterval: () => live(run.data?.status),
  });
  const graph = useQuery({ queryKey: ["graph", code, pipeline], queryFn: () => getJson<Graph>(`${project(code)}/graph`, { pipeline_code: pipeline }) });
  const order = new Map((graph.data?.waves ?? []).flat().map((name, index) => [name, index]));
  const ordered = [...(steps.data?.steps ?? [])].sort((a, b) => (order.get(a.task_code) ?? 0) - (order.get(b.task_code) ?? 0));
  if (run.isError) return <Notice>{(run.error as Error).message}</Notice>;
  const r = run.data;
  if (!r) return <Loading what="run" />;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={r.status} />
          <span className="num text-muted">#{r.pipeline_run_id}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RunTools code={code} run={r} canRun={canRun} />
          <RecoverRun code={code} run={r} canRun={canRun} />
        </div>
      </div>
      {r.run_label ? (
        <p className="m-0 flex items-center gap-2 font-mono text-xs text-muted" aria-label="Run identifier">
          <span className="break-all">{r.run_label}</span>
          <Button size="icon" variant="ghost" className="size-6" aria-label="Copy the run identifier" onClick={() => void navigator.clipboard.writeText(r.run_label ?? "").then(() => toast("Run identifier copied."))}>
            <Copy className="size-3.5" aria-hidden />
          </Button>
        </p>
      ) : null}
      <FactList inline>
        <Fact inline label="Started">{formatTime(r.start_date, tz)}</Fact>
        <Fact inline label="Ended">{formatTime(r.end_date, tz)}</Fact>
        <Fact inline label="Duration">{formatDuration(r.start_date, r.end_date)}</Fact>
        <Fact inline label="Logical date">{r.run_date ?? "—"}</Fact>
        <Fact inline label="Trigger">{r.trigger_kind.toLowerCase()}</Fact>
        <Fact inline label="Started by">{r.started_by ?? "—"}</Fact>
        {r.sla_status ? <Fact inline label="SLA">{r.sla_status}</Fact> : null}
      </FactList>
      <ScopeControls code={code} pipeline={pipeline} runId={runId} elsewhere={["RECOVER"]} />
      <div className="overflow-hidden rounded-lg border border-border">
        <Table aria-label="Task list">
          <thead>
            <tr>
              <Th className="w-8">
                <span className="sr-only">Details</span>
              </Th>
              <Th>Task</Th>
              <Th>Status</Th>
              <Th>Handler</Th>
              <Th>Runs when</Th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((step) => {
              const isOpen = step.task_code === task;
              const toggle = () => onTask(isOpen ? null : step.task_code);
              return (
                <React.Fragment key={step.task_code}>
                  <tr className={isOpen ? "bg-surface-2" : "hover:bg-surface-2"}>
                    <Td className="w-8">
                      <button type="button" className="flex cursor-pointer items-center text-muted hover:text-fg" aria-expanded={isOpen} aria-label={`${isOpen ? "Hide" : "Show"} details of ${step.task_code}`} onClick={toggle}>
                        {isOpen ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
                      </button>
                    </Td>
                    <Td>
                      <button type="button" className="cursor-pointer font-medium text-accent hover:underline" aria-pressed={isOpen} onClick={toggle}>
                        {step.task_code}
                      </button>
                    </Td>
                    <Td>
                      <StatusBadge status={step.status ?? "QUEUED"} />
                    </Td>
                    <Td>{step.handler}</Td>
                    <Td className="text-muted">{step.run_condition ? step.run_condition.toLowerCase() : "all upstream succeed"}</Td>
                  </tr>
                  {isOpen ? (
                    <tr>
                      <td colSpan={5} className="p-0">
                        <div ref={panel}>
                          <TaskDetails code={code} pipeline={pipeline} runId={runId} task={step.task_code} handler={step.handler} />
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </React.Fragment>
              );
            })}
          </tbody>
        </Table>
      </div>
    </div>
  );
}
