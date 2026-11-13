import { RunLabel, copyRunLabel } from "@/components/run-label";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, CircleX, Copy, Download, LifeBuoy } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { Fact, FactList, Loading, Notice, ParamList } from "@/components/common";
import { DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { ActionButton } from "@/components/action-button";
import { AttemptDetails } from "@/components/attempt-details";
import { useToast } from "@/components/toast";
import { DANGER, EFFECT, label as actionLabel, ScopeControls } from "@/components/scope-controls";
import { isFailure, slaVerdict, StatusBadge, taskStatus } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Table, Td, Th } from "@/components/ui/table";
import { useCanRun } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { handlerLabel, runConditionLabel, words } from "@/lib/labels";
import { When } from "@/components/when";
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
        Runs when {runConditionLabel(condition, required)}.{retry ? <> Retry at <When iso={retry} />.</> : ""}
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
      {/* The message is shown once: on the attempt that recorded it, or here when no attempt did. */}
      {run?.error_message && !run.attempts.some((a) => a.error_message === run.error_message) ? <Notice mono>{run.error_message}</Notice> : null}
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

/**
 * Everything else that can be done to the run, in one menu beside its one primary action: each control says what
 * it does, the run's key and logs are at the bottom, and controls that are not possible now say why.
 */
function RunActions({ code, run, canRun }: { code: string; run: RunView; canRun: boolean }) {
  const toast = useToast();
  const [chosen, setChosen] = React.useState<string | null>(null);
  const caps = useQuery({
    queryKey: ["capabilities", code, run.pipeline_code, run.pipeline_run_id, ""],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
    enabled: canRun,
  });
  const query = `pipeline_code=${encodeURIComponent(run.pipeline_code)}&run_id=${run.pipeline_run_id}`;
  const scope = `run ${run.pipeline_run_id}`;
  // Recover is the primary button beside this menu, so it is not repeated here.
  const actions = (caps.data?.actions ?? []).filter((a) => a.action !== "RECOVER");
  const open = actions.filter((a) => a.available);
  const blocked = actions.filter((a) => !a.available);
  const reconcile = canRun && !run.end_date;
  const item = (id: string, title: string, line: string, danger = false) => (
    <DropdownItem key={id} onSelect={() => setChosen(id)} className="grid gap-0.5">
      <span className={danger ? "font-medium text-bad" : "font-medium"}>{title}</span>
      <span className="max-w-72 text-xs text-muted">{line}</span>
    </DropdownItem>
  );
  const file = (path: string, name: string, text: string) => (
    <DropdownItem asChild>
      <a href={`${project(code)}${path}?${query}`} download={name}>
        <Download className="size-4" aria-hidden /> {text}
      </a>
    </DropdownItem>
  );
  return (
    <>
      <DropdownMenu>
        <DropdownTrigger asChild>
          <Button variant="outline" aria-label="Run actions, logs and key">
            Actions
            <ChevronDown className="size-3.5" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent align="end" className="w-80">
          {canRun ? (
            <>
              {open.map((a) => item(a.action, actionLabel(a.action), EFFECT[a.action] ?? "", DANGER.has(a.action)))}
              {reconcile ? item("RECONCILE", "Reconcile", "Records attempts whose owner stopped renewing its lease as lost, so their tasks can be retried.") : null}
              {open.length || reconcile ? <DropdownSeparator /> : null}
            </>
          ) : null}
          <DropdownItem onSelect={() => void navigator.clipboard.writeText(run.run_key).then(() => toast("Run key copied."))}>
            <Copy className="size-4" aria-hidden /> Copy run key
          </DropdownItem>
          {file("/run-log", `run-${run.pipeline_run_id}.log`, "Download run log")}
          {file("/run-zip", `run-${run.pipeline_run_id}-logs.zip`, "Download logs (zip)")}
          {canRun && blocked.length ? (
            <>
              <DropdownSeparator />
              <DropdownLabel>Not available now</DropdownLabel>
              {blocked.map((a) => (
                <DropdownItem key={a.action} disabled className="grid gap-0.5 data-[disabled]:cursor-default">
                  <span className="font-medium text-muted">{actionLabel(a.action)}</span>
                  <span className="max-w-72 text-xs text-muted">{a.reason}</span>
                </DropdownItem>
              ))}
            </>
          ) : null}
        </DropdownContent>
      </DropdownMenu>
      {open.map((a) => (
        <ActionButton<ControlView>
          key={a.action}
          code={code}
          label={actionLabel(a.action)}
          title={`${actionLabel(a.action)} ${scope}`}
          effect={`${EFFECT[a.action] ?? ""} ${a.preserves_successful_work ? "Work that already succeeded is kept." : "Work that already succeeded may be replaced."}`.trim()}
          endpoint="/controls"
          body={(reason) => ({ pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, action: a.action, reason })}
          describe={(r) => `${actionLabel(a.action)} requested: control #${r.control_id}. ${r.message}`}
          menu={{ open: chosen === a.action, setOpen: (on) => setChosen(on ? a.action : null) }}
        />
      ))}
      {reconcile ? (
        <ActionButton<{ message: string }>
          code={code}
          label="Reconcile"
          title={`Reconcile ${run.pipeline_code} run #${run.pipeline_run_id}`}
          effect="Fences attempts whose owner stopped renewing their lease and records them as LOST, so their tasks can be retried; live attempts are untouched."
          endpoint="/reconciliations"
          body={(reason) => ({ pipeline_code: run.pipeline_code, reason })}
          describe={(r) => r.message}
          menu={{ open: chosen === "RECONCILE", setOpen: (on) => setChosen(on ? "RECONCILE" : null) }}
        />
      ) : null}
    </>
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
          describe={(r) => `Recover accepted: control #${r.control_id}${r.execution_run_id ? `, execution #${r.execution_run_id} ${copyRunLabel(r.execution_run_label ?? "")}` : ""}. ${r.message}`}
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

/** Explain recorded skips from their failed dependency, rather than inferring from position. */
function SkipReason({ code, pipeline, runId, task }: { code: string; pipeline: string; runId: number; task: string }) {
  const why = useQuery({
    queryKey: ["explain", code, pipeline, runId, task],
    queryFn: () => getJson<Explanation>(`${project(code)}/explanations`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  const failed = why.data?.dependencies.filter((dependency) => !dependency.met && isFailure(dependency.status));
  return failed?.length ? <span className="text-xs text-muted">Skipped: {failed.map((dependency) => dependency.upstream).join(", ")} failed</span> : null;
}

function FirstError({ code, pipeline, runId, task }: { code: string; pipeline: string; runId: number; task: string }) {
  const history = useQuery({
    queryKey: ["task-history", code, pipeline, runId, task],
    queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  const entry = history.data?.entries[0];
  const message = entry?.error_message ?? [...(entry?.attempts ?? [])].reverse().find((a) => a.error_message)?.error_message;
  if (!message) return null;
  return <p className="m-0 line-clamp-2 break-words font-mono text-xs text-fg">{message.split("\n")[0]}</p>;
}

/**
 * A failed run leads with its failure: which tasks failed, the first one's message, and a button that opens each
 * in the list below, so the cause is read before the run's details.
 */
function FailedTasks({ code, pipeline, runId, steps, open }: { code: string; pipeline: string; runId: number; steps: Steps["steps"]; open: (task: string) => void }) {
  const failed = steps.filter((step) => isFailure(step.status));
  if (failed.length === 0) return null;
  const skipped = steps.filter((step) => step.status === "SKIPPED").length;
  return (
    <section aria-label="Failed tasks" className="grid gap-1.5 rounded-md border border-bad/40 bg-bad-bg px-3 py-2.5 text-[13px] text-bad">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CircleX aria-hidden className="size-4 shrink-0" />
        <span className="font-semibold">
          {failed.length} task{failed.length === 1 ? "" : "s"} failed:
        </span>
        {failed.map((step, i) => (
          <React.Fragment key={step.task_code}>
            {i > 0 ? <span aria-hidden>,</span> : null}
            <button type="button" onClick={() => open(step.task_code)} className="cursor-pointer font-mono font-medium underline underline-offset-2 hover:no-underline">
              {step.task_code}
            </button>
          </React.Fragment>
        ))}
        {skipped ? <span className="text-fg">· {skipped} skipped</span> : null}
      </div>
      <FirstError code={code} pipeline={pipeline} runId={runId} task={failed[0]!.task_code} />
    </section>
  );
}

/**
 * The selected run: its state, identifier, times and controls, and one task table whose rows open in place
 * to the task's attempts, evidence and log. The task open is the address's, so a grid cell can open it.
 */
export function RunOverview({ code, pipeline, runId, task, onTask }: { code: string; pipeline: string; runId: number; task: string | null; onTask: (task: string | null) => void }) {
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
  if (r.pipeline_code !== pipeline)
    return (
      <Notice>
        Run #{r.pipeline_run_id} belongs to {r.pipeline_code}, not {pipeline}.{" "}
        <Link className="underline" to={`/projects/${encodeURIComponent(code)}/pipelines/${encodeURIComponent(r.pipeline_code)}?run=${r.pipeline_run_id}`}>
          Open it in {r.pipeline_code}
        </Link>
        .
      </Notice>
    );
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={r.status} className="px-2 py-0.5 text-sm" />
          <span aria-label="Run identifier"><RunLabel id={r.pipeline_run_id} label={r.run_label} /></span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RecoverRun code={code} run={r} canRun={canRun} />
          <RunActions code={code} run={r} canRun={canRun} />
        </div>
      </div>
      {r.run_label ? (
        <p className="m-0 flex items-center gap-2 font-mono text-xs text-muted">
          <Button size="icon" variant="ghost" className="size-6" aria-label="Copy the run identifier" onClick={() => void navigator.clipboard.writeText(copyRunLabel(r.run_label ?? "")).then(() => toast("Run identifier copied."))}>
            <Copy className="size-3.5" aria-hidden />
          </Button>
        </p>
      ) : null}
      {r.parameter_overrides && Object.keys(r.parameter_overrides).length > 0 && <section aria-label="Recorded task inputs" className="space-y-2">
        <h3 className="text-sm font-medium">Recorded task inputs</h3>
        <ParamList entries={Object.entries(r.parameter_overrides).flatMap(([task, values]) => Object.entries(values).map(([name, value]): [string, string] => [`${task}.${name}`, value]))} />
      </section>}
      <FailedTasks code={code} pipeline={pipeline} runId={runId} steps={ordered} open={(name) => onTask(name)} />
      <FactList inline>
        <Fact inline label="Started"><When iso={r.start_date} /></Fact>
        <Fact inline label="Ended"><When iso={r.end_date} empty="Not yet" /></Fact>
        <Fact inline label="Duration">{formatDuration(r.start_date, r.end_date)}</Fact>
        <Fact inline label="Logical date">{r.run_date ?? "—"}</Fact>
        <Fact inline label="Trigger">{words(r.trigger_kind).toLowerCase()}</Fact>
        <Fact inline label="Started by">{r.started_by ?? "—"}</Fact>
        {slaVerdict(r) ? <Fact inline label="SLA"><StatusBadge status={slaVerdict(r)!} /></Fact> : null}
      </FactList>
      <div data-card className="overflow-hidden rounded-sm border border-border">
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
                      <button type="button" className="cursor-pointer font-medium text-fg hover:text-accent hover:underline" aria-pressed={isOpen} onClick={toggle}>
                        {step.task_code}
                      </button>
                      {step.task_run_id ? <div><RunLabel id={step.task_run_id} label={step.task_run_label} /></div> : null}
                    </Td>
                    <Td>
                      <StatusBadge quiet status={taskStatus(step.status, r)} />
                      {step.status === "SKIPPED" ? <SkipReason code={code} pipeline={pipeline} runId={runId} task={step.task_code} /> : null}
                    </Td>
                    <Td>{handlerLabel(step.handler)}</Td>
                    <Td className="text-muted">{runConditionLabel(step.run_condition, step.run_condition_count)}</Td>
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
