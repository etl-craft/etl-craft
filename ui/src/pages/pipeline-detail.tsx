import { PipelinePause } from "@/components/pipeline-pause";
import { catalogPath } from "@/lib/routes";
import { AccessTab } from "@/pages/admin/access";
import { RunLabel } from "@/components/run-label";
import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import { Check, ChevronDown, ChevronLeft, ChevronRight, PlayCircle } from "lucide-react";
import * as React from "react";
import { AppLink } from "@/components/navigation";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/segmented";
import { ChecklistFilter } from "@/components/tag-filter";
import { Switch } from "@/components/switch";
import { Breadcrumbs, Fact, FactList, Field, inputClass, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { AuditTab, OverviewTab, pipelineTabs } from "@/components/pipeline-tabs";
import { StatusBadge, statusMeta, taskStatus } from "@/components/status";

/** Run states the server records; a task can also not have started in a run. */
const RUN_STATES = ["IN-PROGRESS", "QUEUED", "FAILED", "SUCCESS", "SKIPPED", "CANCELLED"];
const TASK_STATES = [...RUN_STATES, "NOT_STARTED"];
/** The run counts the grid offers. */
const RUN_COUNTS = [1, 5, 10, 25, 50];
import { PauseState } from "@/components/pipeline-parts";
import { RunGraph } from "@/components/lazy-run-graph";
import { DEFAULT_RUNS, GRID_COLUMNS, MIN_TASKS, RunGrid } from "@/components/run-grid";
import { PipelineRefresh, RefreshMenuItem } from "@/components/pipeline-refresh";
import { TaskDefinitionPanel } from "@/components/task-definition-panel";
import { RunOverview } from "@/components/run-overview";
import { RunTimeline } from "@/components/run-timeline";
import { RunsPanel } from "@/components/runs-panel";
import { useRuns } from "@/components/runs-table";
import { Tabs } from "@/components/tabs";
import { SplitPane } from "@/components/split-pane";
import { Card } from "@/components/ui/card";
import { autoStarts } from "@/lib/auto-starts";
import { unavailableAction, useActionAvailability, useAutoStarts, useProjectInfo, useRunReference } from "@/hooks";
import { describeCron, formatDuration } from "@/lib/format";
import { ApiError, getJson, project } from "@/lib/api";
import { pipelinesPath, projectHomePath, runPath, scheduledPath, taskPath } from "@/lib/routes";
import { cn } from "@/lib/utils";
import type { Graph, Pipeline, RunView, Steps } from "@/lib/types";
import { useDocumentTitle } from "@/title";

export function PipelineDetail() {
  const { project: code = "", pipeline = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab") ?? "";
  const askedView = params.get("view");
  const hideBars = params.get("bars") === "off";
  const flow = params.get("flow") === "lr" ? "LR" : params.get("flow") === "tb" ? "TB" : undefined;
  const asLabel = params.get("run") ?? "";
  const numeric = /^[1-9]\d*$/.test(asLabel) && Number.isSafeInteger(Number(asLabel)) ? Number(asLabel) : undefined;
  const addressed = useRunReference(code, numeric === undefined ? asLabel : "");
  const chosen = numeric ?? addressed.data?.pipeline_run_id;
  const task = params.get("task");
  // Gantt shows one run's tasks beside the grid's rows, so it needs a selected run.
  const view = askedView === "graph" ? "graph" : askedView === "gantt" && chosen !== undefined ? "gantt" : "grid";
  const listParam = (key: string) => (params.get(key) ?? "").split(",").filter(Boolean);
  const pickedTasks = listParam("tasks");
  const taskStates = listParam("task_status");
  const runStates = listParam("run_status");
  const filters = { pool: params.get("pool") ?? "", agent: params.get("agent") ?? "", failure_class: params.get("failure_class") ?? "" };
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const navigate = useNavigate();
  const availability = useActionAvailability(code, pipeline);
  const info = useProjectInfo(code);
  const found = useQuery({
    queryKey: ["pipeline", code, pipeline],
    queryFn: () => getJson<Pipeline>(`${project(code)}/pipelines/${encodeURIComponent(pipeline)}`),
    refetchInterval: 15_000,
  });
  const graph = useQuery({ queryKey: ["graph", code, pipeline], queryFn: () => getJson<Graph>(`${project(code)}/graph`, { pipeline_code: pipeline }) });
  const runsKey = `etl-craft-runs:${code}:${pipeline}`;
  const remembered = (() => {
    try {
      return Number(window.localStorage.getItem(runsKey));
    } catch {
      return 0;
    }
  })();
  // The address wins, then what this pipeline's grid was last set to, then the default.
  const wanted = Math.min(200, Math.max(1, Number(params.get("runs")) || remembered || DEFAULT_RUNS));
  const [gridSelection, setGridSelection] = React.useState<{ scope: string; run: number; extra?: number }>();
  const gridExtra = gridSelection?.scope === runsKey && gridSelection?.run === chosen ? gridSelection?.extra : chosen;
  const list = useRuns(code, pipeline, { run_status: runStates.length ? runStates : undefined }, { limit: Math.min(wanted, 100), selected: gridExtra });
  const all = list.all;
  const pages = list.runs.data?.pages;
  const readError = list.runs.error;
  const cells = React.useMemo(() => pages?.flatMap((page) => page.cells ?? []) ?? [], [pages]);
  // The runs asked for are loaded a page at a time until there are enough.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list.runs;
  React.useEffect(() => {
    if (all.length < wanted && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [all.length, wanted, hasNextPage, isFetchingNextPage, fetchNextPage]);
  const runs = all;
  const [gridPage, setGridPage] = React.useState(0);
  const gridRuns = runs.slice(gridPage * wanted, (gridPage + 1) * wanted);
  const older = async () => {
    if (runs.length <= (gridPage + 1) * wanted && hasNextPage) await fetchNextPage();
    setGridPage(gridPage + 1);
  };
  const selected = chosen ?? runs[0]?.pipeline_run_id;
  // A link to a run older than the grid's columns still opens it: the run is read by its number and shown as a column of its own.
  const outside = selected !== undefined && !gridRuns.some((r) => r.pipeline_run_id === selected);
  const extraRun = pages?.[0]?.extra_run ?? (chosen === undefined ? undefined : runs.find(run => run.pipeline_run_id === chosen));
  useDocumentTitle(selected === undefined ? pipeline : `${pipeline} #${selected}`, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const starts = autoStarts(useAutoStarts(), info.project?.allowed_auto_restarts);
  const selectedRun = [...runs, ...(extraRun ? [extraRun] : [])].find((r) => r.pipeline_run_id === selected);
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, selected],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: selected }),
    enabled: view === "graph" && selected !== undefined,
    refetchInterval: selectedRun?.status === "IN-PROGRESS" ? 5_000 : false,
  });
  const tabs=pipelineTabs();
  // A run or task chosen in the URL replaces the pipeline's tabs with that run's or task's view.
  // A task named without a run opens its definition (lookups, offsets, pauses) under the pipeline's tabs.
  const inSelection = selected !== undefined && chosen !== undefined;
  const tab=tabs.some(item=>item.id===asked)?asked:"overview";
  const state = params.get("status") ?? "";
  const select = (runId: number, taskCode?: string) => {
    setGridSelection({ scope: runsKey, run: runId, extra: gridExtra });
    const next = new URLSearchParams(params);
    next.set("run", String(runId));
    next.delete("tab");
    next.delete("try");
    next.delete("instance");
    if (taskCode) next.set("task", taskCode);
    else next.delete("task");
    setParams(next, { replace: true });
  };
  const allTasks = pages?.[0]?.task_order ?? [];
  // Task status reads one column, like a spreadsheet: the selected run, else the newest run shown.
  const statusRun = chosen ?? gridRuns[0]?.pipeline_run_id;
  const stateOf = new Map(cells.filter((cell) => cell.pipeline_run_id === statusRun).map((cell) => [cell.task_code, cell.status as string]));
  const taskOrder = allTasks.filter((name) => (!pickedTasks.length || pickedTasks.includes(name))
    && (!taskStates.length || taskStates.includes(stateOf.get(name) ?? "NOT_STARTED")));
  // The Gantt view reads the selected run's recorded queue and execution times (shared with its run view).
  const ganttRun = useQuery({
    queryKey: ["run", code, chosen],
    queryFn: () => getJson<RunView>(`${project(code)}/runs/${chosen}`),
    enabled: view === "gantt" && chosen !== undefined,
    refetchInterval: (query) => (query.state.data?.status === "IN-PROGRESS" ? 5_000 : false),
  });
  const clearSelection = () => {
    const next = new URLSearchParams(params);
    for (const key of ["run", "task", "try", "instance", "tab"]) next.delete(key);
    setParams(next, { replace: true });
  };
  const apply = (value: string) => {
    const n = Math.min(200, Math.max(1, Math.round(Number(value)) || DEFAULT_RUNS));
    try {
      window.localStorage.setItem(runsKey, String(n));
    } catch {
      /* the count lasts for this page only */
    }
    setGridPage(0);
    choose("runs", null);
  };
  const choose = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const [focused, setFocused] = React.useState<string | null>(null);
  const [runDate, setRunDate] = React.useState("");
  const [runParams, setRunParams] = React.useState("");
  const [requestKey, setRequestKey] = React.useState("");
  const [fullRefresh, setFullRefresh] = React.useState(false);
  const [refreshTask, setRefreshTask] = React.useState("");
  const [refreshOpen, setRefreshOpen] = React.useState(false);
  const [refreshDownstream, setRefreshDownstream] = React.useState(false);
  /** The append targets the server asked to confirm emptying, and whether the person accepted. */
  const [toEmpty, setToEmpty] = React.useState<string[]>([]);
  const [emptyOk, setEmptyOk] = React.useState(false);
  const rescope = (change: () => void) => {
    change();
    setToEmpty([]);
    setEmptyOk(false);
  };
  const p = found.data;

  if(asked==="tasks"||asked==="details"){
    const next=new URLSearchParams(params);next.set("tab","overview");
    return <Navigate replace to={`?${next}`}/>;
  }
  if(asked==="calendar")return <Navigate replace to={scheduledPath(code,pipeline)}/>;
  if (numeric === undefined && asLabel && addressed.isError) return <Notice>{(addressed.error as Error).message}</Notice>;
  if (numeric === undefined && asLabel && addressed.isPending) return <Loading what="the selected run" />;
  if (found.isError) return <Notice>{(found.error as Error).message}</Notice>;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <Breadcrumbs trail={[{ label: code, to: projectHomePath(code) }, { label: "Pipelines", to: pipelinesPath(code) }, { label: pipeline }]} />
      {/* The confirmation lives outside the Options menu, which closes when an item is chosen. */}
      <div hidden>
        <PipelineRefresh code={code} pipeline={pipeline} onDone={() => void found.refetch()} menu={{ open: refreshOpen, setOpen: setRefreshOpen }} />
      </div>
      <PageHeader
        compact
        back={{ to: pipelinesPath(code), label: "Pipelines" }}
        title={pipeline}
        subtitle={p && p.pipeline_name !== pipeline ? p.pipeline_name : undefined}
        status={p ? <PauseState pipeline={p} /> : null}
        actions={
          p ? (
            <div className="flex flex-wrap items-start justify-end gap-2">
              <ActionButton<{ message?: string }>
                code={code}
                label="Run now"
                unavailableReason={unavailableAction(availability, "/runs")}
                title={`Run ${pipeline} now`}
                effect="Admits one manual run of the whole pipeline for the controller; scheduled runs are unaffected."
                endpoint="/runs"
                canSubmit={!(fullRefresh && toEmpty.length > 0 && !emptyOk)}
                onError={(error) => {
                  if (error instanceof ApiError && error.status === 428) {
                    setToEmpty(error.targets);
                    setEmptyOk(false);
                  }
                }}
                body={(reason) => ({ pipeline_code: pipeline, reason, ...(fullRefresh ? { full_refresh: true, ...(refreshTask.trim() ? { task_code: refreshTask.trim(), with_downstream: refreshDownstream } : {}), ...(toEmpty.length > 0 && emptyOk ? { empty_targets: toEmpty } : {}) } : {}), ...(runDate ? { run_date: runDate } : {}), ...(runParams.trim() ? { params: runParams.split("\n").filter((value) => value.trim()), request_key: requestKey } : {}) })}
                describe={(r) => r.message ?? "Run requested."}
                icon={<PlayCircle className="size-4" aria-hidden />}
                variant="primary"
                fields={
                  <div className="space-y-3">
                    <Field label="Logical date (optional)">
                      <input type="date" value={runDate} onChange={(event) => setRunDate(event.target.value)} className={inputClass} />
                    </Field>
                    <Field label="Task input overrides (optional)">
                      <textarea name="params" autoComplete="off" spellCheck={false} value={runParams} onChange={(event) => setRunParams(event.target.value)} className={`${inputClass} h-auto py-2`} rows={3} aria-describedby="run-overrides-help" />
                    </Field>
                    <p id="run-overrides-help" className="text-xs text-muted">One TASK.PARAM=VALUE per line. Existing data inputs only; configuration stays unchanged.</p>
                    <Switch checked={fullRefresh} onChange={() => rescope(() => setFullRefresh(!fullRefresh))} label="Full refresh, once" />
                    {fullRefresh && (
                      <div className="space-y-3 rounded-md border border-border p-3">
                        <p className="m-0 text-xs text-muted">Incremental tasks read everything again and keep the position they reach, so the next run is incremental. A reason is required.</p>
                        <Field label="Only this task (optional)">
                          <input name="refresh_task" autoComplete="off" spellCheck={false} value={refreshTask} onChange={(event) => rescope(() => setRefreshTask(event.target.value))} className={inputClass} placeholder="Task code; empty refreshes every task" />
                        </Field>
                        {refreshTask.trim() && <Switch checked={refreshDownstream} onChange={() => rescope(() => setRefreshDownstream(!refreshDownstream))} label="Include the tasks that read it" />}
                        {toEmpty.length > 0 && (
                          <>
                            <Notice warn>
                              Every source row is read again, so these append targets are emptied just before they load. etl-craft cannot restore them: <strong>{toEmpty.join(", ")}</strong>
                            </Notice>
                            <Switch checked={emptyOk} onChange={() => setEmptyOk(!emptyOk)} label={`Empty ${toEmpty.join(", ")} first, then load it again`} />
                          </>
                        )}
                      </div>
                    )}
                    {runParams.trim() && <Field label="Submission key">
                      <input name="request_key" autoComplete="off" spellCheck={false} value={requestKey} onChange={(event) => setRequestKey(event.target.value)} className={inputClass} required maxLength={128} />
                    </Field>}
                  </div>
                }
              />
              <PipelinePause code={code} pipeline={p}/>
            </div>
          ) : null
        }
      >
        {p ? (
          <FactList inline>
            <Fact inline label="Schedule">{p.run_schedule ? <span title={p.run_schedule}>{describeCron(p.run_schedule) ?? <code className="font-mono">{p.run_schedule}</code>}</span> : "Not scheduled"}</Fact>
            <Fact inline label="Latest run">
              {p.latest_whole_run ? (
                <span className="inline-flex items-center gap-1.5">
                  <StatusBadge status={p.latest_whole_run.status} /> <When iso={p.latest_whole_run.start_date} />
                </span>
              ) : (
                "None yet"
              )}
            </Fact>
            <Fact inline label="Next run">{p.starts_on_upload && !p.run_schedule ? "On upload" : p.waits_for_events && !p.run_schedule ? "Waits for object events" : starts && !starts.schedule ? <span className="text-muted" title="Schedules are switched off here by the controller or the project">Not started here</span> : <When iso={p.next_run} empty={p.restart_note ?? "—"} />}</Fact>
            <Fact inline label="Refresh">{p.refresh_type.toLowerCase()}</Fact>
            <Fact inline label="SLA">{p.sla_in_hours?`${p.sla_in_hours} h`:"None"}</Fact>
            <Fact inline label="Restarts">{p.restart_note??"On its schedule only"}</Fact>
            <Fact inline label="Tasks">{graph.data?.waves.flat().length??"…"}</Fact>
            <Fact inline label="Tags">{p.tags.length?p.tags.join(", "):"None"}</Fact>
          </FactList>
        ) : (
          <Loading what="pipeline" />
        )}
      </PageHeader>
      <SplitPane
        // The graph keeps its own wider split; the grid and Gantt give most of the width to the details.
        key={view === "graph" ? "graph" : "grid"}
        id={view === "graph" ? "pipeline-graph" : "pipeline-grid"}
        initial={view === "graph" ? 0.7 : 0.3}
        minimumLeft={view === "graph" ? 0 : MIN_TASKS + 6 + GRID_COLUMNS.id.minimum + 24}
        // On a narrow screen the selected run's details come before the grid of every run.
        narrowFirst={inSelection ? "right" : "left"}
        className="lg:min-h-0 lg:flex-1"
        left={
        <Card className="flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden">
          <div className="grid gap-1.5 border-b border-border px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Segmented label="Run view" value={view} options={[{ id: "grid", label: "Grid" }, ...(chosen !== undefined ? [{ id: "gantt", label: "Gantt" }] : []), { id: "graph", label: "Graph" }]} onSelect={(id) => choose("view", id === "grid" ? null : id)} />
              {view === "graph" ? (
              <Segmented
                label="Graph direction"
                value={flow ?? null}
                options={[{ id: "LR", label: "Horizontal" }, { id: "TB", label: "Vertical" }].map((o) => ({ ...o, title: flow === o.id ? `${o.label}; select again for automatic` : o.label }))}
                onSelect={(id) => choose("flow", flow === id ? null : id.toLowerCase())}
              />
              ) : (
                <DropdownMenu>
                  <DropdownTrigger asChild>
                    <Button size="sm" variant="outline">
                      Options
                      <ChevronDown className="size-3.5" aria-hidden />
                    </Button>
                  </DropdownTrigger>
                  <DropdownContent>
                    <DropdownLabel>Runs shown</DropdownLabel>
                    {RUN_COUNTS.map((count) => (
                      <DropdownItem key={count} onSelect={() => apply(String(count))}>
                        <Check className={cn("size-4", wanted !== count && "invisible")} aria-hidden /> {count} runs
                      </DropdownItem>
                    ))}
                    <DropdownSeparator />
                    <DropdownItem onSelect={() => choose("bars", hideBars ? null : "off")}>
                      <Check className={cn("size-4", hideBars && "invisible")} aria-hidden /> Duration bars
                    </DropdownItem>
                    <DropdownSeparator />
                    <RefreshMenuItem code={code} pipeline={pipeline} onSelect={() => setRefreshOpen(true)} />
                  </DropdownContent>
                </DropdownMenu>
              )}
            </div>
            {view !== "graph" ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <ChecklistFilter label="Tasks" noun="tasks" one="task" known={allTasks} selected={pickedTasks} onChange={(next) => choose("tasks", next.join(",") || null)} />
                <ChecklistFilter label={`Task status${statusRun === undefined ? "" : ` in #${statusRun}`}`} noun="statuses" one="status" known={TASK_STATES} selected={taskStates}
                  name={(state) => statusMeta(state).label} onChange={(next) => choose("task_status", next.join(",") || null)} />
                <ChecklistFilter label="Run status" noun="statuses" one="status" known={RUN_STATES} selected={runStates}
                  name={(state) => statusMeta(state).label} onChange={(next) => { setGridPage(0); choose("run_status", next.join(",") || null); }} />
                <span className="ml-auto flex">
                  <Button size="icon" variant="ghost" title="Older runs" aria-label="Older runs" disabled={isFetchingNextPage || (!hasNextPage && runs.length <= (gridPage + 1) * wanted)} onClick={() => void older()}><ChevronLeft className="size-4" aria-hidden /></Button>
                  <Button size="icon" variant="ghost" title="Newer runs" aria-label="Newer runs" disabled={gridPage === 0} onClick={() => setGridPage(gridPage - 1)}><ChevronRight className="size-4" aria-hidden /></Button>
                </span>
              </div>
            ) : null}
          </div>
          <div className={cn("relative min-h-56 flex-1 overflow-hidden", view !== "grid" && "max-lg:min-h-96")}>
            {!graph.isSuccess ? (
              graph.isError ? <Notice className="m-3">{(graph.error as Error).message}</Notice> : <Loading what="tasks" className="p-3" />
            ) : view === "gantt" && chosen !== undefined ? (
              <section aria-label="Timeline" className="min-h-0 flex-1 overflow-auto p-3" data-scroll-area>
                {ganttRun.data ? <RunTimeline run={ganttRun.data} compact order={taskOrder} /> : ganttRun.isError ? <Notice>{ganttRun.error.message}</Notice> : <Loading what="the run's timeline" />}
              </section>
            ) : view !== "graph" ? (
              readError ? <Notice>{readError.message}</Notice> : list.runs.isPending ? <Loading what="run history" className="p-3" /> :
              <RunGrid code={code} pipeline={pipeline} graph={graph.data} tasks={taskOrder} runs={gridRuns} cells={cells} extra={outside ? extraRun ?? undefined : undefined} selected={chosen} task={task} onSelect={select} bars={!hideBars} />
            ) : (
              <div className="absolute inset-0 flex flex-col">
              {selectedRun ? (
                <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-2 px-3 py-1.5 text-xs">
                  <RunLabel id={selectedRun.pipeline_run_id} label={selectedRun.run_label} />
                  <StatusBadge status={selectedRun.status} />
                  <span className="text-muted"><When iso={selectedRun.start_date} /></span>
                  <span className="num text-muted">{formatDuration(selectedRun.start_date, selectedRun.end_date)}</span>
                </div>
              ) : null}
              {selected !== undefined && !steps.isSuccess ? (
                steps.isError ? <Notice className="m-3">{(steps.error as Error).message}</Notice> : <Loading what="task statuses" className="p-3" />
              ) : null}
              <div className="relative min-h-0 flex-1">
              <RunGraph
                catalogDetails={taskCode=>catalogPath(code,"tasks",`${pipeline}.${taskCode}`)}
                fill
                direction={flow}
                graph={graph.data}
                statuses={Object.fromEntries((steps.data?.steps ?? []).map((step) => [step.task_code, taskStatus(step.status, selectedRun)]))}
                plain={!steps.isSuccess}
                focused={focused}
                onFocus={setFocused}
                onOpen={(taskCode) => (selected === undefined ? navigate(taskPath(code, pipeline, taskCode)) : select(selected, taskCode))}
              />
              </div>
              </div>
            )}
          </div>
        </Card>
        }
        right={
        <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {inSelection ? (
            <nav aria-label="Selection" className="flex flex-wrap items-center gap-1 border-b border-border px-3 py-2 text-sm">
              <Button size="sm" variant="ghost" onClick={clearSelection}>{pipeline}</Button>
              <span aria-hidden className="text-muted">›</span>
              {task ? <Button size="sm" variant="ghost" onClick={() => select(selected, undefined)}>Run #{selected}</Button> : <span aria-current="page" className="px-2 font-medium">Run #{selected}</span>}
              <Button asChild size="sm" variant="ghost"><AppLink to={runPath(code, pipeline, selected, task ?? undefined)}>Open run</AppLink></Button>
              {task ? <><span aria-hidden className="text-muted">›</span><span aria-current="page" className="break-all px-2 font-medium">{task}</span></> : null}
            </nav>
          ) : (
            <div className="px-3">
              <Tabs tabs={tabs} value={tab} onChange={(id) => choose("tab", id)} />
            </div>
          )}
          <div role="tabpanel" id="tabpanel" data-scroll-area aria-labelledby={inSelection ? undefined : `tab-${tab}`} aria-label={inSelection ? (task ? `Task ${task}` : `Run #${selected}`) : undefined} className="min-h-0 flex-1 overflow-auto p-4">
            {inSelection ? null : <h2 className="sr-only">{tabs.find(item=>item.id===tab)?.label}</h2>}
            {inSelection ? (
              <RunOverview code={code} pipeline={pipeline} runId={selected} task={task}
                taskOrder={taskOrder} cells={cells} tab={params.get("instance") ?? ""}
                tryNumber={params.has("try") ? Number(params.get("try")) : null}
                onTask={(name) => select(selected, name ?? undefined)}
                onTab={(next) => choose("instance", next)} onTry={(value) => {
                  const next = new URLSearchParams(params);
                  if (value === null) next.delete("try");
                  else next.set("try", String(value));
                  next.delete("instance");
                  setParams(next, { replace: true });
                }} />
            ) : tab === "runs" ? (
              <RunsPanel
                code={code}
                pipeline={pipeline}
                bars={false}
                status={state || undefined}
                filters={{ pool: filters.pool || undefined, agent: filters.agent || undefined, failure_class: filters.failure_class || undefined }}
                highlight={selected}
                toolbar={
                  <>
                    <SelectField compact label="State" value={state} onChange={(value) => choose("status", value || null)}>
                      <option value="">All states</option>
                      {["FAILED", "IN-PROGRESS", "SUCCESS", "SKIPPED", "LOST"].map((s) => (
                        <option key={s} value={s}>
                          {s === "IN-PROGRESS" ? "Running" : s.charAt(0) + s.slice(1).toLowerCase()}
                        </option>
                      ))}
                    </SelectField>
                    <Field compact label="Pool">
                      <input value={filters.pool} onChange={(event) => setFilter("pool", event.target.value)} className={inputClass} placeholder="Any pool" />
                    </Field>
                    <Field compact label="Agent id">
                      <input value={filters.agent} onChange={(event) => setFilter("agent", event.target.value.replace(/\D/g, ""))} inputMode="numeric" className={inputClass} placeholder="Any agent" />
                    </Field>
                    <SelectField compact label="Failure class" value={filters.failure_class} onChange={(value) => setFilter("failure_class", value)}>
                      <option value="">Any</option>
                      {["TRANSIENT", "PERMANENT", "UNKNOWN"].map((c) => (
                        <option key={c} value={c}>
                          {c.charAt(0) + c.slice(1).toLowerCase()}
                        </option>
                      ))}
                    </SelectField>
                  </>
                }
              />
            ) : task && chosen === undefined ? (
              <TaskDefinitionPanel code={code} pipeline={pipeline} task={task} />
            ) : !p || !graph.isSuccess ? (
              <Loading what="pipeline" />

            ) : tab === "audit" ? (
              <AuditTab code={code} pipeline={pipeline} />
            ) : tab === "access" ? (
              <AccessTab key={`${code}:${pipeline}`} project={code} projects={[code]} pipeline={pipeline} />

            ) : (
              <OverviewTab code={code} pipeline={p} runs={runs} />
            )}
          </div>
        </Card>
        }
      />
    </div>
  );
}
