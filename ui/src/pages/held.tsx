import { RunLabel } from "@/components/run-label";
import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, useParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { EmptyState, Loading, Notice, PageHeader } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useCanRun, useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { pipelinePath, runPath } from "@/lib/routes";
import type { Hold, Pipeline, TaskPause } from "@/lib/types";
import { useDocumentTitle } from "@/title";

type Standing = TaskPause & { pipeline_code: string };
const holds = createColumnHelper<Hold>();
const pauses = createColumnHelper<Pipeline>();
const standing = createColumnHelper<Standing>();
const result = (r: { message?: string }) => r.message ?? "Request recorded.";

export function Held() {
  const { project: code = "" } = useParams();
  const canRun = useCanRun(code);
  const info = useProjectInfo(code);
  useDocumentTitle("Held and paused", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const list = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`), refetchInterval: 15_000 });
  const held = useQuery({ queryKey: ["holds", code], queryFn: () => getJson<{ holds: Hold[] }>(`${project(code)}/holds`), refetchInterval: 15_000 });
  const paused = (list.data?.pipelines ?? []).filter((p) => p.paused);
  const tasks: Standing[] = (list.data?.pipelines ?? []).flatMap((p) => p.task_pauses.map((t) => ({ ...t, pipeline_code: p.pipeline_code })));
  const failed = list.error ?? held.error;
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Held and paused" subtitle="Everything waiting on a person. A pause stops new runs of a pipeline or task; a hold stops one run, or one task in a run, from starting." />
      {failed ? <Notice>{(failed as Error).message}</Notice> : null}
      {list.isPending || held.isPending ? <Loading what="holds" /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Held runs and tasks · {held.data?.holds.length ?? 0}</CardTitle>
        </CardHeader>
        <DataTable find
          label="Held runs and tasks"
          data={held.data?.holds ?? []}
          empty={held.isSuccess ? <EmptyState title="Nothing is held." nextStep="Hold a queued or running task from its run page when work must wait." /> : undefined}
          columns={[
            holds.accessor("pipeline_code", { header: "Pipeline", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            holds.accessor("pipeline_run_id", { header: "Run", cell: (c) => <RunLabel id={c.getValue()} label={c.row.original.run_label} to={runPath(code, c.row.original.pipeline_code, c.getValue())} /> }),
            holds.accessor("task_code", { header: "Held", cell: (c) => c.getValue() ?? "Whole run" }),
            holds.accessor("requested_by", { header: "By" }),
            holds.accessor("requested_at", { header: "Since", cell: (c) => <When iso={c.getValue()} /> }),
            holds.accessor("reason", { header: "Reason", cell: (c) => c.getValue() ?? "" }),
            ...(canRun
              ? [
                  holds.display({
                    id: "act",
                    header: "Actions",
                    cell: (c) => (
                      <ActionButton<{ message?: string }>
                        code={code}
                        label="Release"
                        title={`Release ${c.row.original.task_code ?? "the whole run"}`}
                        effect={`Lets ${c.row.original.task_code ? `task ${c.row.original.task_code} in` : ""} run ${c.row.original.pipeline_run_id} of ${c.row.original.pipeline_code} start.`}
                        endpoint="/controls"
                        body={(reason) => ({ pipeline_code: c.row.original.pipeline_code, action: "RELEASE", run_id: c.row.original.pipeline_run_id, ...(c.row.original.task_code ? { task_code: c.row.original.task_code } : {}), reason })}
                        describe={result}
                        size="sm"
                      />
                    ),
                  }),
                ]
              : []),
          ]}
        />
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Paused pipelines · {paused.length}</CardTitle>
        </CardHeader>
        <DataTable find
          label="Paused pipelines"
          data={paused}
          empty={list.isSuccess ? <EmptyState title="No pipeline is paused." nextStep="Pause a pipeline from Pipelines to prevent new automatic runs." /> : undefined}
          columns={[
            pauses.accessor("pipeline_code", { header: "Pipeline", cell: (c) => <Link className="font-medium text-fg hover:text-accent hover:underline" to={pipelinePath(code, c.getValue())}>{c.getValue()}</Link> }),
            pauses.display({ id: "by", header: "By", cell: (c) => c.row.original.paused?.paused_by }),
            pauses.display({ id: "since", header: "Since", cell: (c) => <When iso={c.row.original.paused?.paused_at} /> }),
            pauses.display({ id: "reason", header: "Reason", cell: (c) => c.row.original.paused?.reason }),
            ...(canRun
              ? [
                  pauses.display({
                    id: "act",
                    header: "Actions",
                    cell: (c) => (
                      <ActionButton<{ message?: string }>
                        code={code}
                        label="Resume"
                        title={`Resume ${c.row.original.pipeline_code}`}
                        effect="Allows automatic runs again; the next scheduled run is waited for."
                        endpoint="/controls"
                        body={(reason) => ({ pipeline_code: c.row.original.pipeline_code, action: "RESUME", reason, then: "wait" })}
                        describe={result}
                        size="sm"
                      />
                    ),
                  }),
                ]
              : []),
          ]}
        />
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Paused tasks · {tasks.length}</CardTitle>
        </CardHeader>
        <DataTable find
          label="Paused tasks"
          data={tasks}
          empty={list.isSuccess ? <EmptyState title="No task is paused." nextStep="Pause a task from its history page when future starts must wait." /> : undefined}
          columns={[
            standing.accessor("pipeline_code", { header: "Pipeline", cell: (c) => <Link className="font-medium text-fg hover:text-accent hover:underline" to={pipelinePath(code, c.getValue())}>{c.getValue()}</Link> }),
            standing.accessor("task_code", { header: "Task" }),
            standing.accessor("outcome", { header: "Downstream sees", cell: (c) => c.getValue() ?? "Waiting" }),
            standing.accessor("expires_at", { header: "Ends", cell: (c) => <When iso={c.getValue()} empty="Until resumed" /> }),
            standing.accessor("actor", { header: "By" }),
            standing.accessor("reason", { header: "Reason" }),
            ...(canRun
              ? [
                  standing.display({
                    id: "act",
                    header: "Actions",
                    cell: (c) => (
                      <ActionButton<{ message?: string }>
                        code={code}
                        label="Resume"
                        title={`Resume task ${c.row.original.task_code}`}
                        effect={`Ends the standing pause of ${c.row.original.task_code} in ${c.row.original.pipeline_code}.`}
                        endpoint="/controls"
                        body={(reason) => ({ pipeline_code: c.row.original.pipeline_code, task_code: c.row.original.task_code, action: "RESUME", reason })}
                        describe={result}
                        size="sm"
                      />
                    ),
                  }),
                ]
              : []),
          ]}
        />
      </Card>
    </div>
  );
}
