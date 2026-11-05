import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { ArrowLeft, Download } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { Fact, FactList, Loading, Notice, PageHeader, ParamList } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectInfo, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { downloadCsv, toCsv } from "@/lib/csv";
import { formatDuration, formatTime } from "@/lib/format";
import { pipelinePath, runPath } from "@/lib/routes";
import type { Pipeline, TaskDefinition, TaskHistory, TaskOffset, TaskRunView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const RUNS = 50;
const columns = createColumnHelper<TaskRunView>();
const n = (value: number | null) => (value === null ? <span className="text-muted">—</span> : value.toLocaleString("en-GB"));
const seconds = (run: TaskRunView) => (run.start_date && run.end_date ? (new Date(run.end_date).getTime() - new Date(run.start_date).getTime()) / 1000 : null);

export function Task() {
  const { project: code = "", pipeline = "", task = "" } = useParams();
  const tz = useTimezone();
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
  const exportCsv = () =>
    downloadCsv(
      `${pipeline}-${task}-runs.csv`,
      toCsv(
        ["run", "status", "started", "seconds", "rows_in", "inserted", "updated", "deleted", "rejected", "duplicates", "attempts"],
        runs.map((r) => [r.pipeline_run_id, r.status, r.start_date, seconds(r), r.source_count, r.insert_count, r.update_count, r.delete_count, r.reject_count, r.duplicate_count, r.attempt_count]),
      ),
    );
  return (
    <div className="grid grid-cols-1 gap-5">
      <Link to={pipelinePath(code, pipeline, "tasks")} className="inline-flex w-fit items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> {pipeline} tasks
      </Link>
      <PageHeader
        title={task}
        subtitle={`${pipeline} · ${code}`}
        status={paused ? <span className="text-warn">Paused by {paused.actor}: {paused.reason}</span> : null}
        actions={
          <Button onClick={exportCsv} disabled={runs.length === 0}>
            <Download className="size-4" aria-hidden /> Export CSV
          </Button>
        }
      >
        <FactList className="lg:grid-cols-4">
          <Fact label="Runs shown">{runs.length}</Fact>
          <Fact label="Succeeded">{runs.filter((r) => r.status === "SUCCESS").length} of {runs.length}</Fact>
          <Fact label="Average duration">{average === null ? "No finished runs" : formatDuration("2000-01-01T00:00:00Z", new Date(Date.parse("2000-01-01T00:00:00Z") + average * 1000).toISOString())}</Fact>
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
            columns.accessor("status", { header: "Status", cell: (c) => <StatusBadge status={c.getValue()} /> }),
            columns.accessor("start_date", { header: "Started", cell: (c) => <span className="num whitespace-nowrap">{c.getValue() ? formatTime(c.getValue(), tz) : "Not started"}</span> }),
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
                <Fact label="Handler">{def.data.handler}</Fact>
                {def.data.merge_key.length ? <Fact label="Merge key">{def.data.merge_key.join(", ")}</Fact> : null}
                {def.data.merge_columns.length ? <Fact label="Compared columns"><span className="break-words">{def.data.merge_columns.join(", ")}</span></Fact> : null}
                <Fact label="Kept between runs">
                  {offset.data?.kind ? `${offset.data.kind} · ${offset.data.offset_type ?? ""} ${offset.data.offset_value ?? ""}`.trim() : "Nothing"}
                </Fact>
              </FactList>
              <ParamList entries={Object.entries(def.data.parameters).sort(([x], [y]) => x.localeCompare(y))} />
            </>
          ) : (
            <Loading what="the definition" />
          )}
        </div>
      </Card>
    </div>
  );
}
