import { TaskDefinitionPanel } from "@/components/task-definition-panel";
import { copyRunLabel } from "@/components/run-label";
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Copy, Download, LifeBuoy } from "lucide-react";
import { AppLink as Link } from "@/components/navigation";
import { Fact, FactList, Loading, Notice, ParamList, SelectField } from "@/components/common";
import { Disclosure, DisclosureSummary, DropdownContent, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { ActionButton } from "@/components/action-button";
import { AttemptDetails, AttemptLog, LIVE } from "@/components/attempt-details";
import { useToast } from "@/components/toast";
import { controlAnswers, DANGER, EFFECT, label as actionLabel, ScopeControls } from "@/components/scope-controls";
import { isFailure, slaVerdict, StatusBadge, solidClass, taskStatus } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Table, Td, Th } from "@/components/ui/table";
import { unavailableAction, useActionAvailability } from "@/hooks";
import { getJson, getText, project } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { Tabs } from "@/components/tabs";
import { handlerLabel, runConditionLabel, words } from "@/lib/labels";
import { When, useNow } from "@/components/when";
import { itemsPath } from "@/lib/routes";
import type { Capabilities, ControlView, Explanation, GridCell, RunView, Steps, TaskHistory } from "@/lib/types";

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

const taskTabs = [
  { id: "logs", label: "Logs" }, { id: "source", label: "SQL / script" },
  { id: "details", label: "Details" }, { id: "attempts", label: "Attempts" },
];

function TaskSource({ code, pipeline, runId, task, attemptId }: {
  code: string; pipeline: string; runId: number; task: string; attemptId?: number;
}) {
  const source = useQuery({
    queryKey: ["task-source", code, pipeline, runId, task],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: runId, source_task: task }),
  });
  const log = useQuery({
    queryKey: ["task-source-log", code, attemptId],
    queryFn: () => getText(`${project(code)}/attempts/${attemptId}/log`),
    enabled: attemptId !== undefined,
    retry: false,
  });
  const excerpt = (log.data ?? "").split("\n").flatMap((line) => {
    const match = /SQL_SCRIPT .* statement \d+ starting: (.*)$/.exec(line);
    return match ? [match[1]] : [];
  });
  const deployed = source.data?.source;
  return <div className="grid gap-3">
    {source.isPending ? <Loading what="deployed source" /> : null}
    {source.error ? <Notice>{source.error.message}</Notice> : null}
    {deployed ? <section className="grid gap-2">
      <h3 className="text-sm font-semibold">Source (version {deployed.version}, as deployed for this run)</h3>
      {deployed.file ? <p className="break-all text-xs text-muted">{deployed.file}</p> : null}
      {deployed.text === null ? <p className="text-sm text-muted">This handler has no SQL or script source.</p>
        : <pre className="whitespace-pre-wrap break-all rounded-md bg-surface-2 p-3 text-xs">{deployed.text}</pre>}
      {deployed.truncated_at_bytes !== null ? <p className="text-xs text-muted">Source display truncated at UTF-8 byte {deployed.truncated_at_bytes.toLocaleString()} (256 KiB limit).</p> : null}
    </section> : null}
    {excerpt.length ? <section className="grid gap-2">
      <h3 className="text-sm font-semibold">Execution text recorded for this try (first 240 characters per statement)</h3>
      <pre className="whitespace-pre-wrap break-all rounded-md bg-surface-2 p-3 text-xs">{excerpt.join("\n")}</pre>
    </section> : <p className="text-sm text-muted">Exact, masked per-try execution capture is planned for S7.AX.4.</p>}
  </div>;
}

function TaskDetails({ code, pipeline, run, task, handler, cell, tab, tryNumber, onTab, onTry }: {
  code: string; pipeline: string; run: RunView; task: string; handler?: string; cell?: GridCell;
  tab: string; tryNumber: number | null; onTab: (tab: string) => void;
  onTry: (value: number | null) => void;
}) {
  const panel = React.useRef<HTMLElement>(null);
  React.useLayoutEffect(() => {
    const area = panel.current?.closest("[data-scroll-area]");
    area?.scrollTo(0, 0);
    // Stacked on a phone, bring the details card into view only when it is off-screen; scrolling it to the
    // very top would carry it away again as the content above it settles.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      (area?.parentElement ?? panel.current)?.scrollIntoView({ block: "nearest" });
    }
  }, []);
  const runId = run.pipeline_run_id;
  const now = useNow();
  const history = useQuery({
    queryKey: ["task-history", code, pipeline, runId, task],
    queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
    refetchInterval: run.status === "IN-PROGRESS" ? 3_000 : false,
  });
  const summary = history.data?.entries[0];
  const attempts = summary?.attempts ?? [];
  const latest = attempts.at(-1);
  const attempt = tryNumber === null ? latest : attempts.find(item => item.attempt_number === tryNumber);
  const start = attempt?.started_at ?? cell?.start_date;
  const end = attempt ? attempt.ended_at : cell?.end_date;
  const selectedTab = taskTabs.some(item => item.id === tab) ? tab : "logs";
  const status = attempt?.status ?? taskStatus(summary?.status ?? cell?.status ?? null, run);
  return <section ref={panel} aria-label={`Task ${task}`} className="grid scroll-mt-14 gap-3">
    <div className="flex flex-wrap items-center gap-2">
      <h2 className="break-all text-lg font-semibold">{task}</h2>
      <StatusBadge status={status} />
      <span className="text-xs text-muted">Run #{runId}</span>
      {handler ? <span className="text-xs text-muted">{handlerLabel(handler)}</span> : null}
      {attempt && attempt.attempt_number > 1 ? <span className="text-xs">Try {attempt.attempt_number}</span> : null}
    </div>
    <FactList inline>
      {start ? <Fact inline label="Started"><When iso={start} now={!end ? Math.max(now, Date.parse(start)) : now} /></Fact> : null}
      {end ? <Fact inline label="Ended"><When iso={end} /></Fact> : null}
      {start ? <Fact inline label="Duration">{formatDuration(start, end ?? null, now)}</Fact> : null}
    </FactList>
    {attempts.length > 1 ? <SelectField compact label="Try" value={String(tryNumber ?? "")} onChange={(value) => onTry(value ? Number(value) : null)}>
      <option value="">Latest ({latest?.attempt_number})</option>
      {attempts.filter(item => item !== latest).map(item => <option key={item.attempt_id} value={item.attempt_number}>{item.attempt_number}</option>)}
    </SelectField> : null}
    <Tabs tabs={taskTabs} value={selectedTab} onChange={onTab} panelId="task-instance-tab" />
    <div role="tabpanel" id="task-instance-tab" aria-labelledby={`tab-${selectedTab}`} className="grid gap-3">
    {history.isError ? <Notice>{history.error.message}</Notice> : null}
    {history.isPending ? <Loading what="task history" /> : null}
    {history.isSuccess && tryNumber !== null && !attempt ? <Notice>Try {tryNumber} is not recorded for {task} in run #{runId}.</Notice> : null}
    {selectedTab === "logs" && attempt ? (attempt.log_path || LIVE.has(attempt.status)
      ? <AttemptLog key={attempt.attempt_id} code={code} attempt={attempt} open embedded />
      : <p className="m-0 text-sm text-muted">No log was recorded for this attempt.</p>) : null}
    {selectedTab === "logs" && history.isSuccess && !attempt && tryNumber === null ? <p className="text-sm text-muted">This task has no stored attempt log yet.</p> : null}
    {selectedTab === "source" ? <TaskSource code={code} pipeline={pipeline} runId={runId} task={task} attemptId={attempt?.attempt_id} /> : null}
    {selectedTab === "details" ? <>
      {attempt ? <AttemptDetails code={code} attempt={attempt} hideLog /> : null}
      <ScopeControls code={code} pipeline={pipeline} runId={runId} task={task} />
      {handler === "PYTHON" ? <Link to={itemsPath(code, pipeline, runId, task)} className="text-accent hover:underline">Items</Link> : null}
      {summary && summary.status !== "SUCCESS" ? <Why code={code} pipeline={pipeline} runId={runId} task={task} /> : null}
      <Disclosure>
        <DisclosureSummary>Task definition and history</DisclosureSummary>
        <TaskDefinitionPanel code={code} pipeline={pipeline} task={task} />
      </Disclosure>
    </> : null}
    {selectedTab === "attempts" ? <ul className="grid gap-1">
      {attempts.map(item => <li key={item.attempt_id} className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => onTry(item === latest ? null : item.attempt_number)}>Try {item.attempt_number}</Button>
        <StatusBadge status={item.status} />
      </li>)}
    </ul> : null}
    </div>
  </section>;
}

/**
 * Everything else that can be done to the run, in one menu beside its one primary action: each control says what
 * it does, the run's key and logs are at the bottom, and controls that are not possible now say why.
 */
function RunActions({ code, run }: { code: string; run: RunView }) {
  const toast = useToast();
  const [chosen, setChosen] = React.useState<string | null>(null);
  const caps = useQuery({
    queryKey: ["capabilities", code, run.pipeline_code, run.pipeline_run_id, ""],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
  });
  const query = `pipeline_code=${encodeURIComponent(run.pipeline_code)}&run_id=${run.pipeline_run_id}`;
  const scope = `run ${run.pipeline_run_id}`;
  // Recover is the primary button beside this menu, so it is not repeated here.
  const actions = controlAnswers(caps.data, caps.error).filter((a) => a.action !== "RECOVER");
  const open = actions.filter((a) => a.available);
  const availability = useActionAvailability(code, run.pipeline_code, true, { run_id: run.pipeline_run_id });
  const reconcileReason = unavailableAction(availability, "/reconciliations");
  const item = (id: string, title: string, line: string, danger = false, unavailable?: string) => (
    <DropdownItem key={id} aria-label={title} unavailableReason={unavailable} onSelect={() => setChosen(id)} className="grid gap-0.5">
      <span className={danger ? "font-medium text-bad" : "font-medium"}>{title}</span>
      {!unavailable ? <span className="max-w-72 text-xs text-muted">{line}</span> : null}
    </DropdownItem>
  );
  const file = (path: string, name: string, text: string) => (
    <DropdownItem asChild unavailableReason={unavailableAction(availability, path, "GET")}>
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
          {actions.map((a) => item(a.action, actionLabel(a.action), EFFECT[a.action] ?? "", DANGER.has(a.action), a.available ? undefined : a.reason ?? undefined))}
          {item("RECONCILE", "Reconcile", "Records attempts whose owner stopped renewing its lease as lost, so their tasks can be retried.", false, reconcileReason)}
          <DropdownSeparator />
          <DropdownItem onSelect={() => void navigator.clipboard.writeText(run.run_key).then(() => toast("Run key copied."))}>
            <Copy className="size-4" aria-hidden /> Copy run key
          </DropdownItem>
          {file("/run-log", `run-${run.pipeline_run_id}.log`, "Download run log")}
          {file("/run-zip", `run-${run.pipeline_run_id}-logs.zip`, "Download logs (zip)")}
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
      <ActionButton<{ message: string }>
        code={code}
        label="Reconcile"
        title={`Reconcile ${run.pipeline_code} run #${run.pipeline_run_id}`}
        effect="Fences attempts whose owner stopped renewing their lease and records them as LOST, so their tasks can be retried; live attempts are untouched."
        endpoint="/reconciliations"
        unavailableReason={reconcileReason}
        body={(reason) => ({ pipeline_code: run.pipeline_code, reason })}
        describe={(r) => r.message}
        menu={{ open: chosen === "RECONCILE", setOpen: (on) => setChosen(on ? "RECONCILE" : null) }}
      />
    </>
  );
}

function RecoverRun({ code, run }: { code: string; run: RunView }) {
  const caps = useQuery({
    queryKey: ["capabilities", code, run.pipeline_code, run.pipeline_run_id, run.status],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id }),
  });
  const capability = controlAnswers(caps.data, caps.error).find((a) => a.action === "RECOVER");
  return (
    <ActionButton<ControlView>
      code={code}
      label="Recover run"
      unavailableReason={capability?.available ? undefined : capability?.reason ?? "Availability is unavailable."}
      title={`Recover run #${run.pipeline_run_id}`}
      effect={`Reopens ${run.pipeline_code} run #${run.pipeline_run_id}: tasks that succeeded are kept; failed and unfinished tasks run again.`}
      endpoint="/controls"
      body={(reason) => ({ pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, action: "RECOVER", reason })}
      describe={(r) => `Recover accepted: control #${r.control_id}${r.execution_run_id ? `, execution #${r.execution_run_id} ${copyRunLabel(r.execution_run_label ?? "")}` : ""}. ${r.message}`}
      icon={<LifeBuoy className="size-4" aria-hidden />}
      variant="primary"
    />
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

// Gantt and Graph are views of the panel beside the grid, so the run keeps only its own tabs.
const runTabs = [{ id: "instances", label: "Task instances" }, { id: "details", label: "Details" }];

export function RunOverview({ code, pipeline, runId, task, taskOrder, cells, tab, tryNumber, onTask, onTab, onTry }: {
  code: string; pipeline: string; runId: number; task: string | null; taskOrder: string[]; cells: GridCell[];
  tab: string; tryNumber: number | null; onTask: (task: string | null) => void;
  onTab: (tab: string) => void; onTry: (value: number | null) => void;
}) {
  const toast = useToast();
  const now = useNow();
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
  if (run.isError) return <Notice>{run.error.message}</Notice>;
  const r = run.data;
  if (!r) return <Loading what="run" />;
  if (r.pipeline_code !== pipeline) return <Notice>Run #{runId} belongs to {r.pipeline_code}.</Notice>;
  const byTask = new Map(steps.data?.steps.map(step => [step.task_code, step]));
  const byCell = new Map(cells.filter(cell => cell.pipeline_run_id === runId).map(cell => [cell.task_code, cell]));
  if (task) return <TaskDetails key={`${runId}:${task}`} code={code} pipeline={pipeline} run={r} task={task} handler={byTask.get(task)?.handler}
    cell={byCell.get(task)} tab={tab} tryNumber={tryNumber} onTab={onTab} onTry={onTry} />;
  const active = runTabs.some(item => item.id === tab) ? tab : "instances";
  const duration = (cell?: GridCell) => cell?.start_date ? Math.max(0, (cell.end_date ? Date.parse(cell.end_date) : now) - Date.parse(cell.start_date)) : 0;
  const max = Math.max(1, ...Array.from(byCell.values(), duration));
  return <div className="grid gap-3">
    <div className="flex flex-wrap items-center gap-2">
      <h2 aria-label="Run identifier" title={r.run_label} className="text-base font-semibold">Run #{runId}</h2>
      <StatusBadge status={r.status} />
      {r.selected_task_ids?.length ? <span className="text-xs">{r.selected_task_ids.length} of {taskOrder.length} tasks</span> : null}
      <RecoverRun code={code} run={r} /><RunActions code={code} run={r} />
      {r.run_label ? <Button size="icon" variant="ghost" aria-label="Copy the run identifier" onClick={() => void navigator.clipboard.writeText(copyRunLabel(r.run_label ?? "")).then(() => toast("Run identifier copied."))}><Copy className="size-4" aria-hidden /></Button> : null}
    </div>
    <FactList inline>
      {r.run_date ? <Fact inline label="Run date">{r.run_date}</Fact> : null}
      <Fact inline label="Trigger">{words(r.trigger_kind)}</Fact>
      {r.started_by ? <Fact inline label="Started by">{r.started_by}</Fact> : null}
      {r.start_date ? <Fact inline label="Started"><When iso={r.start_date} /></Fact> : null}
      {r.end_date ? <Fact inline label="Ended"><When iso={r.end_date} /></Fact> : null}
      {r.start_date ? <Fact inline label="Duration">{formatDuration(r.start_date, r.end_date, now)}</Fact> : null}
    </FactList>
    {/* Inputs given for this run change what it does, so they show with the run's facts, not behind a tab. */}
    {r.parameter_overrides && Object.keys(r.parameter_overrides).length > 0 ? <section aria-label="Recorded task inputs" className="grid gap-1">
      <h3 className="text-sm font-medium">Recorded task inputs</h3>
      <ParamList entries={Object.entries(r.parameter_overrides).flatMap(([name, values]) => Object.entries(values).map(([key, value]): [string, string] => [`${name}.${key}`, value]))} />
    </section> : null}
    <Tabs tabs={runTabs} value={active} onChange={onTab} panelId="run-instance-tab" />
    <div role="tabpanel" id="run-instance-tab" aria-labelledby={`tab-${active}`} className="grid gap-3">
    {active === "details" ? <>
      {slaVerdict(r) ? <StatusBadge status={slaVerdict(r)!} /> : null}
    </> : null}
    {active === "instances" ? <>
      {steps.isError ? <Notice>{steps.error.message}</Notice> : null}
      <Table aria-label="Task instances" className="stacked-table" unwrapped>
        <thead><tr><Th>Task</Th><Th>Status</Th><Th>Try</Th><Th>Started</Th><Th>Duration</Th><Th>Runs when</Th></tr></thead>
        <tbody>{taskOrder.map(name => {
          const step = byTask.get(name);
          const cell = byCell.get(name);
          const status = taskStatus(step?.status ?? cell?.status ?? null, r);
          return <tr key={name}>
            <Td><button type="button" className="break-all text-left font-medium text-accent hover:underline" onClick={() => onTask(name)}>{name}</button></Td>
            <Td data-label="Status"><StatusBadge quiet status={status} />{step?.status === "SKIPPED" ? <SkipReason code={code} pipeline={pipeline} runId={runId} task={name} /> : null}</Td>
            <Td data-label="Try">{cell?.attempt_count || ""}</Td><Td data-label="Started">{cell?.start_date ? <When iso={cell.start_date} /> : null}</Td>
            <Td data-label="Duration">{cell?.start_date ? <><span className="num">{formatDuration(cell.start_date, cell.end_date, now)}</span><span aria-hidden className={`block h-1 rounded ${solidClass(status)}`} style={{ width: `${Math.max(4, duration(cell) / max * 100)}%` }} /></> : null}</Td>
            <Td data-label="Runs when">{step?.handler === "ALERT" ? alertCondition(step.parameters?.ALERT_ON) : step ? runConditionLabel(step.run_condition, step.run_condition_count) : null}</Td>
          </tr>;
        })}</tbody>
      </Table>
    </> : null}
    </div>
  </div>;
}

function alertCondition(event: string | undefined): string {
  if (!event) return "On its configured pipeline event";
  return event.split("|").map(value => {
    const label = value.trim().replaceAll("_", " ").toLowerCase();
    return label === "failure" || label === "pipeline failure" ? "When the pipeline fails"
      : label === "success" || label === "pipeline success" ? "When the pipeline succeeds"
        : `On ${label}`;
  }).join(" · ");
}
