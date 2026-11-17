import { useMemo } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { AppLink as Link } from "@/components/navigation";
import { EmptyState, Loading, Notice, PageHeader } from "@/components/common";
import { PipelinePause } from "@/components/pipeline-pause";
import { TaskPauseControl } from "@/components/task-pause";
import { StatusBadge } from "@/components/status";
import { RunLabel } from "@/components/run-label";
import { DataTable } from "@/components/data-table";
import { When } from "@/components/when";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { pausedPath, pipelinePath, runPath } from "@/lib/routes";
import type { Pipeline, TaskPause } from "@/lib/types";
import { useDocumentTitle } from "@/title";

type Standing = TaskPause & { pipeline_code: string };
const pipelines = createColumnHelper<Pipeline>();
const tasks = createColumnHelper<Standing>();

export function HeldRedirect() {
  const { project: code = "" } = useParams();
  const location = useLocation();
  return <Navigate replace to={pausedPath(code) + location.search + location.hash} />;
}

export function Paused() {
  const { project: code = "" } = useParams();
  const info = useProjectInfo(code);
  useDocumentTitle("Paused", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const list = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`), refetchInterval: 15_000 });
  const paused = (list.data?.pipelines ?? []).filter(p => p.paused);
  const standing = (list.data?.pipelines ?? []).flatMap(p => p.task_pauses.map(t => ({ ...t, pipeline_code: p.pipeline_code })));
  const pipelineColumns = useMemo(() => [
    pipelines.accessor("pipeline_code", { header: "Pipeline", cell: c => <Link to={pipelinePath(code,c.getValue())} className="font-medium text-accent hover:underline">{c.getValue()}</Link> }),
    pipelines.display({ id:"mode", header:"Active runs", cell:c=>c.row.original.paused?.active_runs }),
    pipelines.display({ id:"runs", header:"Drained runs", cell:c=><div className="grid gap-1">{c.row.original.paused?.drained_runs.map(run=><RunLabel key={run.pipeline_run_id} id={run.pipeline_run_id} label={run.run_label} to={runPath(code,c.row.original.pipeline_code,run.pipeline_run_id)} />)}</div> }),
    pipelines.display({ id:"by", header:"By", cell:c=>c.row.original.paused?.paused_by }),
    pipelines.display({ id:"since", header:"Since", cell:c=><When iso={c.row.original.paused?.paused_at} /> }),
    pipelines.display({ id:"reason", header:"Reason", cell:c=>c.row.original.paused?.reason }),
    pipelines.display({ id:"actions", header:"Actions", size:210, cell:c=><PipelinePause code={code} pipeline={c.row.original} /> }),
  ], [code]);
  const taskColumns = useMemo(() => [
    tasks.accessor("pipeline_code", {header:"Pipeline",cell:c=><Link to={pipelinePath(code,c.getValue())} className="text-accent hover:underline">{c.getValue()}</Link>}),
    tasks.accessor("task_code", {header:"Task"}),
    tasks.accessor("outcome", {header:"Outcome",cell:c=><StatusBadge status={c.getValue()} />}),
    tasks.display({id:"scope",header:"Scope",cell:()=>"Runs where this task has not started"}),
    tasks.accessor("expires_at", {header:"Ends",cell:c=><When iso={c.getValue()} empty="Until resumed" />}),
    tasks.accessor("actor", {header:"By"}),
    tasks.accessor("reason", {header:"Reason"}),
    tasks.display({id:"actions",header:"Actions",size:210,cell:c=><TaskPauseControl code={code} pipeline={c.row.original.pipeline_code} task={c.row.original.task_code} />})
  ], [code]);
  return <div className="grid grid-cols-1 gap-5">
    <PageHeader title="Paused" subtitle="Pipeline pauses block new runs. DRAIN waits at task boundaries; FINISH lets admitted runs complete. Task pauses supply their recorded outcome before the task starts." />
    {list.isError ? <Notice>{(list.error as Error).message}</Notice> : null}
    {list.isPending ? <Loading what="pauses" /> : null}
    <Card><CardHeader><CardTitle>Paused pipelines · {paused.length}</CardTitle></CardHeader>
      <DataTable find stacked label="Paused pipelines" data={paused}
        empty={list.isSuccess ? <EmptyState title="No pipeline is paused." nextStep="Pause a pipeline from its header or Pipelines row." /> : undefined}
        columns={pipelineColumns} />
    </Card>
    <Card><CardHeader><CardTitle>Paused tasks · {standing.length}</CardTitle></CardHeader>
      <DataTable find stacked label="Paused tasks" data={standing}
        empty={list.isSuccess ? <EmptyState title="No task is paused." nextStep="Pause a task from its history or run details and choose an outcome." /> : undefined}
        columns={taskColumns} />
    </Card>
  </div>;
}
