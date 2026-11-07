import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Pause, Play, PlayCircle } from "lucide-react";
import * as React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownTrigger } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { Fact, FactList, Field, inputClass, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { AuditTab, CalendarTab, DetailsTab, OverviewTab, TasksTab } from "@/components/pipeline-tabs";
import { StatusBadge } from "@/components/status";
import { PauseState } from "@/components/pipeline-parts";
import { RunGraph } from "@/components/run-graph";
import { RunGrid } from "@/components/run-grid";
import { RunOverview } from "@/components/run-overview";
import { RunsPanel } from "@/components/runs-panel";
import { useRuns } from "@/components/runs-table";
import { Tabs } from "@/components/tabs";
import { SplitPane } from "@/components/split-pane";
import { Card } from "@/components/ui/card";
import { useCanRun, useProjectInfo, useTimezone } from "@/hooks";
import { formatTime } from "@/lib/format";
import { getJson, project } from "@/lib/api";
import { pipelinesPath, taskPath } from "@/lib/routes";
import { cn } from "@/lib/utils";
import type { Graph, Pipeline, Steps } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const TAB_IDS = ["overview", "run", "runs", "tasks", "calendar", "audit", "details"];

export function PipelineDetail() {
  const { project: code = "", pipeline = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab") ?? "";
  const view = params.get("view") === "graph" ? "graph" : "grid";
  const hideBars = params.get("bars") === "off";
  const byTime = params.get("columns") === "time";
  const flow = params.get("flow") === "lr" ? "LR" : params.get("flow") === "tb" ? "TB" : undefined;
  const chosen = /^\d+$/.test(params.get("run") ?? "") ? Number(params.get("run")) : undefined;
  const task = params.get("task");
  const filters = { pool: params.get("pool") ?? "", agent: params.get("agent") ?? "", failure_class: params.get("failure_class") ?? "" };
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const navigate = useNavigate();
  const tz = useTimezone();
  const canRun = useCanRun(code);
  const info = useProjectInfo(code);
  const found = useQuery({
    queryKey: ["pipeline", code, pipeline],
    queryFn: () => getJson<Pipeline>(`${project(code)}/pipelines/${encodeURIComponent(pipeline)}`),
    refetchInterval: 15_000,
  });
  const graph = useQuery({ queryKey: ["graph", code, pipeline], queryFn: () => getJson<Graph>(`${project(code)}/graph`, { pipeline_code: pipeline }) });
  const runs = useRuns(code, pipeline).all;
  const selected = chosen ?? runs[0]?.pipeline_run_id;
  useDocumentTitle(selected === undefined ? pipeline : `${pipeline} #${selected}`, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, selected],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: selected }),
    enabled: view === "graph" && selected !== undefined,
  });
  const tab = TAB_IDS.includes(asked) && (asked !== "run" || selected !== undefined) ? asked : chosen !== undefined ? "run" : "overview";
  const tabs = [
    { id: "overview", label: "Overview" },
    ...(selected !== undefined ? [{ id: "run", label: `Run #${selected}` }] : []),
    { id: "runs", label: "Runs" },
    { id: "tasks", label: "Tasks" },
    { id: "calendar", label: "Calendar" },
    { id: "audit", label: "Audit log" },
    { id: "details", label: "Details" },
  ];
  const state = params.get("status") ?? "";
  const select = (runId: number, taskCode?: string) => {
    const next = new URLSearchParams(params);
    next.set("run", String(runId));
    next.delete("tab");
    if (taskCode) next.set("task", taskCode);
    else next.delete("task");
    setParams(next, { replace: true });
  };
  const choose = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const [focused, setFocused] = React.useState<string | null>(null);
  const [runDate, setRunDate] = React.useState("");
  const [then, setThen] = React.useState("wait");
  const p = found.data;

  if (found.isError) return <Notice>{(found.error as Error).message}</Notice>;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <PageHeader
        compact
        back={{ to: pipelinesPath(code), label: "Pipelines" }}
        title={pipeline}
        subtitle={p && p.pipeline_name !== pipeline ? p.pipeline_name : undefined}
        status={p ? <PauseState pipeline={p} /> : null}
        actions={
          p && canRun ? (
            <div className="flex flex-wrap items-start justify-end gap-2">
              <ActionButton<{ message?: string }>
                code={code}
                label="Run now"
                title={`Run ${pipeline} now`}
                effect="Admits one manual run of the whole pipeline for the controller; scheduled runs are unaffected."
                endpoint="/runs"
                body={(reason) => ({ pipeline_code: pipeline, reason, ...(runDate ? { run_date: runDate } : {}) })}
                describe={(r) => r.message ?? "Run requested."}
                icon={<PlayCircle className="size-4" aria-hidden />}
                variant="primary"
                fields={
                  <Field label="Logical date (optional)">
                    <input type="date" value={runDate} onChange={(event) => setRunDate(event.target.value)} className={inputClass} />
                  </Field>
                }
              />
              {p.paused ? (
                <ActionButton<{ message?: string }>
                  code={code}
                  label="Resume"
                  title={`Resume ${pipeline}`}
                  effect="Allows automatic runs again."
                  endpoint="/controls"
                  body={(reason) => ({ pipeline_code: pipeline, action: "RESUME", reason, then })}
                  describe={(r) => r.message ?? "Resume requested."}
                  icon={<Play className="size-4" aria-hidden />}
                  fields={
                    p.run_schedule ? (
                      <SelectField label="After resuming" value={then} onChange={setThen}>
                        <option value="wait">Wait for the next scheduled run</option>
                        <option value="run-now">Run now</option>
                        <option value="catch-up">Catch up missed runs</option>
                      </SelectField>
                    ) : undefined
                  }
                />
              ) : (
                <ActionButton<{ message?: string }>
                  code={code}
                  label="Pause"
                  title={`Pause ${pipeline}`}
                  effect="Stops new automatic runs. Runs already started continue."
                  endpoint="/controls"
                  body={(reason) => ({ pipeline_code: pipeline, action: "PAUSE", reason })}
                  describe={(r) => r.message ?? "Pause requested."}
                  icon={<Pause className="size-4" aria-hidden />}
                />
              )}
            </div>
          ) : null
        }
      >
        {p ? (
          <FactList inline>
            <Fact inline label="Schedule">{p.run_schedule ? <code className="font-mono">{p.run_schedule}</code> : "Not scheduled"}</Fact>
            <Fact inline label="Latest run">
              {runs[0] ? (
                <span className="inline-flex items-center gap-1.5">
                  <StatusBadge status={runs[0].status} /> {formatTime(runs[0].start_date, tz)}
                </span>
              ) : (
                "None yet"
              )}
            </Fact>
            <Fact inline label="Next run">{p.next_run ? formatTime(p.next_run, tz) : (p.restart_note ?? "—")}</Fact>
            <Fact inline label="Refresh">{p.refresh_type.toLowerCase()}</Fact>
            {p.sla_in_hours ? <Fact inline label="SLA">{p.sla_in_hours} h</Fact> : null}
            {p.tags.length ? <Fact inline label="Tags">{p.tags.join(", ")}</Fact> : null}
          </FactList>
        ) : (
          <Loading what="pipeline" />
        )}
      </PageHeader>
      <SplitPane
        id="pipeline"
        className="lg:min-h-0 lg:flex-1"
        left={
        <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
            <div role="group" aria-label="Run view" className="inline-flex rounded-md border border-border p-0.5 text-sm">
              {(["grid", "graph"] as const).map((id) => (
                <button key={id} type="button" aria-pressed={view === id} onClick={() => choose("view", id === "grid" ? null : id)} className={cn("cursor-pointer rounded px-2.5 py-0.5", view === id ? "bg-accent/15 font-medium text-fg" : "text-muted hover:text-fg")}>
                  {id === "grid" ? "Grid" : "Graph"}
                </button>
              ))}
            </div>
            {view === "graph" ? (
              <div role="group" aria-label="Graph direction" className="inline-flex rounded-md border border-border p-0.5 text-xs">
                {([["LR", "Horizontal"], ["TB", "Vertical"]] as const).map(([id, label]) => (
                  <button key={id} type="button" aria-pressed={flow === id} title={flow === id ? `${label}; select again for automatic` : label} onClick={() => choose("flow", flow === id ? null : id.toLowerCase())} className={cn("cursor-pointer rounded px-2 py-0.5", flow === id ? "bg-accent/15 font-medium text-fg" : "text-muted hover:text-fg")}>
                    {label}
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="hidden text-xs text-muted xl:inline">Newest on the right; a dot: not started</span>
                <DropdownMenu>
                  <DropdownTrigger asChild>
                    <Button size="sm" variant="outline">
                      Options
                      <ChevronDown className="size-3.5" aria-hidden />
                    </Button>
                  </DropdownTrigger>
                  <DropdownContent>
                    <DropdownLabel>Grid</DropdownLabel>
                    <DropdownItem onSelect={() => choose("bars", hideBars ? null : "off")}>
                      <Check className={cn("size-4", hideBars && "invisible")} aria-hidden /> Duration bars
                    </DropdownItem>
                    <DropdownItem onSelect={() => choose("columns", byTime ? null : "time")}>
                      <Check className={cn("size-4", !byTime && "invisible")} aria-hidden /> Label columns by start time
                    </DropdownItem>
                  </DropdownContent>
                </DropdownMenu>
              </div>
            )}
          </div>
          <div className={cn("relative min-h-0 flex-1", view === "grid" && "overflow-auto")}>
            {!graph.isSuccess ? (
              graph.isError ? <Notice className="m-3">{(graph.error as Error).message}</Notice> : <Loading what="tasks" className="p-3" />
            ) : view === "grid" ? (
              <RunGrid code={code} pipeline={pipeline} graph={graph.data} runs={runs} selected={selected} onSelect={select} bars={!hideBars} labels={byTime ? "time" : "id"} />
            ) : (
              <div className="absolute inset-0">
              <RunGraph
                fill
                direction={flow}
                graph={graph.data}
                statuses={Object.fromEntries((steps.data?.steps ?? []).map((step) => [step.task_code, step.status ?? "QUEUED"]))}
                plain={selected === undefined}
                focused={focused}
                onFocus={setFocused}
                onOpen={(taskCode) => (selected === undefined ? navigate(taskPath(code, pipeline, taskCode)) : select(selected, taskCode))}
              />
              </div>
            )}
          </div>
        </Card>
        }
        right={
        <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="px-3">
            <Tabs tabs={tabs} value={tab} onChange={(id) => choose("tab", id)} />
          </div>
          <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${tab}`} className="min-h-0 flex-1 overflow-auto p-4">
            {tab === "runs" ? (
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
            ) : tab === "run" && selected !== undefined ? (
              <RunOverview code={code} pipeline={pipeline} runId={selected} task={task} onTask={(next) => choose("task", next)} />
            ) : !p || !graph.isSuccess ? (
              <Loading what="pipeline" />
            ) : tab === "tasks" ? (
              <TasksTab code={code} pipeline={pipeline} graph={graph.data} runId={selected} />
            ) : tab === "calendar" ? (
              <CalendarTab runs={runs} />
            ) : tab === "audit" ? (
              <AuditTab code={code} pipeline={pipeline} />
            ) : tab === "details" ? (
              <DetailsTab code={code} pipeline={p} graph={graph.data} />
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
