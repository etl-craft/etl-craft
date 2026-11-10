import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, useParams } from "react-router-dom";
import { Breadcrumbs, Fact, FactList, Loading, Notice, PageHeader, ParamList } from "@/components/common";
import { CsvButton } from "@/components/csv-button";
import { DataTable } from "@/components/data-table";
import { OffsetCard } from "@/components/offset-card";
import { ProvenanceCard } from "@/components/provenance-card";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatSeconds } from "@/lib/format";
import { handlerLabel } from "@/lib/labels";
import { pipelinePath, pipelinesPath, runPath } from "@/lib/routes";
import type { Pipeline, TaskDefinition, TaskHistory, TaskOffset, TaskRunView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const RUNS = 50;
const columns = createColumnHelper<TaskRunView>();
const n = (value: number | null) => (value === null ? <span className="text-muted">—</span> : value.toLocaleString("en-GB"));
const seconds = (run: TaskRunView) => (run.start_date && run.end_date ? (new Date(run.end_date).getTime() - new Date(run.start_date).getTime()) / 1000 : null);

export function Task() {
  const { project: code = "", pipeline = "", task = "" } = useParams();
  const info = useProjectInfo(code);
  useDocumentTitle(`${task} · ${pipeline}`, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const params = { pipeline_code: pipeline, task_code: task };
  const def = useQuery({ queryKey: ["task", code, pipeline, task], queryFn: () => getJson<TaskDefinition>(`${project(code)}/task`, params) });
  const offset = useQuery({ queryKey: ["offset", code, pipeline, task], queryFn: () => getJson<TaskOffset>(`${project(code)}/offset`, params) });
  const pipe = useQuery({ queryKey: ["pipeline", code, pipeline], queryFn: () => getJson<Pipeline>(`${project(code)}/pipelines/${encodeURIComponent(pipeline)}`) });
  const history = useQuery({ queryKey: ["task-runs", code, pipeline, task], queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { ...params, all: true, limit: RUNS }), refetchInterval: 15_000 });
  const runs = history.data?.entries ?? [];
  const took = runs.map(seconds).filter((s): s is number => s !== null);
  const average = took.length ? took.reduce((a, b) => a + b, 0) / took.length : null;
  const paused = pipe.data?.task_pauses.find((p) => p.task_code === task);
  return (
    <div className="grid grid-cols-1 gap-5">
      <Breadcrumbs
        trail={[
          { label: "Pipelines", to: pipelinesPath(code) },
          { label: pipeline, to: pipelinePath(code, pipeline) },
          { label: "Tasks", to: pipelinePath(code, pipeline, "tasks") },
          { label: task },
        ]}
      />
      <PageHeader
        back={{ to: pipelinePath(code, pipeline, "tasks"), label: `${pipeline} tasks` }}
        title={task}
        subtitle={`${pipeline} · ${code}`}
        status={paused ? <span className="text-idle">Paused by {paused.actor}: {paused.reason}</span> : null}
        actions={
          <CsvButton
            name={`${pipeline}-${task}-runs.csv`}
            header={["run", "status", "started", "seconds", "rows_in", "inserted", "updated", "deleted", "rejected", "duplicates", "attempts"]}
            rows={runs.map((r) => [r.pipeline_run_id, r.status, r.start_date, seconds(r), r.source_count, r.insert_count, r.update_count, r.delete_count, r.reject_count, r.duplicate_count, r.attempt_count])}
          />
        }
      >
        <FactList className="lg:grid-cols-4">
          <Fact label="Runs shown">{runs.length}</Fact>
          <Fact label="Succeeded">{runs.filter((r) => r.status === "SUCCESS").length} of {runs.length}</Fact>
          <Fact label="Average duration">{average === null ? "No finished runs" : formatSeconds(average)}</Fact>
        </FactList>
      </PageHeader>
      {history.isError ? <Notice>{(history.error as Error).message}</Notice> : null}
      {history.isPending ? <Loading what="runs" /> : null}
      <Card>
        <CardHeader>
          <CardTitle>Last {runs.length || ""} runs</CardTitle>
        </CardHeader>
        <DataTable
          label="Task runs"
          data={runs}
          empty={history.isSuccess ? "This task has not run yet." : undefined}
          initialSort={[{ id: "run", desc: true }]}
          columns={[
            columns.accessor("pipeline_run_id", { id: "run", header: "Run", cell: (c) => <Link className="num font-medium text-accent hover:underline" to={runPath(code, pipeline, c.getValue())}>#{c.getValue()}</Link> }),
            columns.accessor("status", { header: "Status", cell: (c) => <StatusBadge quiet status={c.getValue()} /> }),
            columns.accessor("start_date", { header: "Started", cell: (c) => <When iso={c.getValue()} empty="Not started" /> }),
            columns.display({ id: "duration", header: "Duration", cell: (c) => <span className="num">{c.row.original.start_date ? formatDuration(c.row.original.start_date, c.row.original.end_date) : "—"}</span> }),
            columns.accessor("source_count", { header: "Rows in", cell: (c) => <span className="num">{n(c.getValue())}</span> }),
            columns.accessor("insert_count", { header: "Inserted", cell: (c) => <span className="num">{n(c.getValue())}</span> }),
            columns.accessor("update_count", { header: "Updated", cell: (c) => <span className="num">{n(c.getValue())}</span> }),
            columns.accessor("delete_count", { header: "Deleted", cell: (c) => <span className="num">{n(c.getValue())}</span> }),
            columns.accessor("reject_count", { header: "Rejected", cell: (c) => <span className="num">{n(c.getValue())}</span> }),
            columns.accessor("duplicate_count", { header: "Duplicates", cell: (c) => <span className="num">{n(c.getValue())}</span> }),
            columns.accessor("attempt_count", { header: "Attempts", cell: (c) => <span className="num">{c.getValue()}</span> }),
          ]}
        />
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Definition</CardTitle>
        </CardHeader>
        <div className="grid gap-4 p-4">
          {def.isError ? <Notice>{(def.error as Error).message}</Notice> : null}
          {def.data ? (
            <>
              <FactList className="lg:grid-cols-4">
                <Fact label="Handler">{handlerLabel(def.data.handler)}</Fact>
                {def.data.merge_key.length ? <Fact label="Merge key">{def.data.merge_key.join(", ")}</Fact> : null}
                {def.data.merge_columns.length ? <Fact label="Compared columns"><span className="break-words">{def.data.merge_columns.join(", ")}</span></Fact> : null}
              </FactList>
              <ParamList entries={Object.entries(def.data.parameters).sort(([x], [y]) => x.localeCompare(y))} />
            </>
          ) : (
            <Loading what="the definition" />
          )}
        </div>
      </Card>
      {offset.data ? <OffsetCard key={offset.data.offset_value ?? ""} code={code} pipeline={pipeline} task={task} offset={offset.data} runs={runs.map((r) => r.pipeline_run_id)} /> : null}
      {def.data?.merge_key.length ? <ProvenanceCard code={code} pipeline={pipeline} task={task} keys={def.data.merge_key} columns={def.data.merge_columns} /> : null}
    </div>
  );
}
