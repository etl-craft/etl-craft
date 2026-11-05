import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Pause, Play, PlayCircle } from "lucide-react";
import * as React from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { Field, inputClass, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { PauseState, RunBars } from "@/components/pipeline-parts";
import { RunGraph } from "@/components/run-graph";
import { RunsTable } from "@/components/runs-table";
import { Tabs } from "@/components/tabs";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useCanRun, useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { existingPath, pipelinesPath } from "@/lib/routes";
import type { Graph, Pipeline, RunView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const TABS = [
  { id: "runs", label: "Runs" },
  { id: "tasks", label: "Tasks" },
];

export function PipelineDetail() {
  const { project: code = "", pipeline = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "tasks" ? "tasks" : "runs";
  const canRun = useCanRun(code);
  const info = useProjectInfo(code);
  useDocumentTitle(pipeline, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const found = useQuery({
    queryKey: ["pipeline", code, pipeline],
    queryFn: () => getJson<Pipeline>(`${project(code)}/pipelines/${encodeURIComponent(pipeline)}`),
    refetchInterval: 15_000,
  });
  const graph = useQuery({ queryKey: ["graph", code, pipeline], queryFn: () => getJson<Graph>(`${project(code)}/graph`, { pipeline_code: pipeline }), enabled: tab === "tasks" });
  const [runs, setRuns] = React.useState<RunView[]>([]);
  const [focused, setFocused] = React.useState<string | null>(null);
  const [runDate, setRunDate] = React.useState("");
  const [then, setThen] = React.useState("wait");
  const p = found.data;

  if (found.isError) return <Notice>{(found.error as Error).message}</Notice>;
  return (
    <div className="grid grid-cols-1 gap-5">
      <Link to={pipelinesPath(code)} className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> Pipelines
      </Link>
      <PageHeader
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
          <p className="m-0 text-[13px] text-muted">
            {p.run_schedule ? <>Schedule <code className="font-mono">{p.run_schedule}</code></> : "Not scheduled"}
            {p.sla_in_hours ? ` · SLA ${p.sla_in_hours} h` : ""} · {p.refresh_type.toLowerCase()} refresh
          </p>
        ) : (
          <Loading what="pipeline" />
        )}
      </PageHeader>
      <Tabs tabs={TABS} value={tab} onChange={(id) => setParams(id === "runs" ? {} : { tab: id }, { replace: true })} />
      <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${tab}`} className="grid gap-4">
        {tab === "runs" ? (
          <>
            {runs.length ? (
              <Card>
                <CardHeader>
                  <CardTitle>Run durations</CardTitle>
                  <span className="text-xs text-muted">Newest on the right; select a bar to open its run</span>
                </CardHeader>
                <div className="p-4">
                  <RunBars project={code} runs={runs.slice(0, 40)} />
                </div>
              </Card>
            ) : null}
            <RunsTable code={code} pipeline={pipeline} onRuns={setRuns} />
          </>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Tasks and dependencies</CardTitle>
              <span className="text-xs text-muted">Click a task for its lineage; use its arrow to open it</span>
            </CardHeader>
            {graph.isSuccess ? (
              <RunGraph
                graph={graph.data}
                statuses={{}}
                plain
                focused={focused}
                onFocus={setFocused}
                onOpen={(task) => window.location.assign(existingPath(code, `pipelines/${encodeURIComponent(pipeline)}/tasks/${encodeURIComponent(task)}`))}
              />
            ) : graph.isError ? (
              <Notice className="m-4">{(graph.error as Error).message}</Notice>
            ) : (
              <Loading what="tasks" className="p-4" />
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
