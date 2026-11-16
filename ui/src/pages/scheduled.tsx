import { RunCalendar } from "@/components/run-calendar";
import { useRuns } from "@/components/runs-table";
import { Button } from "@/components/ui/button";
import {LegendView,statusEntries} from "@/components/legend";
import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import * as React from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { AppLink as Link } from "@/components/navigation";
import { Loading, Notice, PageHeader, EmptyState, SelectField } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { PauseState, RecentRuns } from "@/components/pipeline-parts";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { AutoStartNotice } from "@/components/auto-start-notice";
import { When } from "@/components/when";
import { useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { pipelinePath } from "@/lib/routes";
import type { Pipeline } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<Pipeline>();

export function Scheduled() {
  const { project: code = "" } = useParams();
  const [params,setParams]=useSearchParams();
  const pipeline=params.get("pipeline")??"";
  const history=useRuns(code,pipeline||undefined);
  const [now] = React.useState(() => Date.now());
  const info = useProjectInfo(code);
  useDocumentTitle("Scheduled runs", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const list = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`), refetchInterval: 15_000 });
  const timed = (list.data?.pipelines ?? []).filter((p) => p.run_schedule);
  const upcoming = timed.filter((p) => p.next_run).sort((a, b) => (a.next_run ?? "").localeCompare(b.next_run ?? "") || a.pipeline_code.localeCompare(b.pipeline_code));
  const stalled = timed.filter((p) => !p.next_run);
  const link = columns.accessor("pipeline_code", {
    header: "Pipeline",
    cell: (c) => (
      <Link className="font-medium text-fg hover:text-accent hover:underline" to={pipelinePath(code, c.getValue())}>
        {c.getValue()}
      </Link>
    ),
  });
  const schedule = columns.accessor("run_schedule", { header: "Schedule", enableSorting: false, cell: (c) => <code className="whitespace-nowrap font-mono text-xs">{c.getValue()}</code> });
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Scheduled runs" subtitle="What runs next" />
      <AutoStartNotice code={code} />
      {list.isError ? <Notice>{(list.error as Error).message}</Notice> : null}
      {list.isPending ? <Loading what="schedules" /> : null}
      <Card>
        <CardHeader>
          <CardTitle>Next runs · {upcoming.length}</CardTitle>
        </CardHeader>
        <LegendView entries={statusEntries(upcoming.flatMap(pipeline=>pipeline.recent_runs.map(run=>run.status)))}><DataTable find
          label="Next runs"
          data={upcoming}
          empty={list.isSuccess ? <EmptyState title="No scheduled pipeline has a next run" nextStep="A pipeline is listed here once its RUN_SCHEDULE is set in the project's config files and automatic runs are on." /> : undefined}
          columns={[
            columns.accessor("next_run", { header: "Next run", enableSorting: false, cell: (c) => <span className="num whitespace-nowrap"><span className="font-medium"><When iso={c.getValue()} now={now} /></span></span> }),
            link,
            schedule,
            columns.display({ id: "recent", header: "Recent runs", cell: (c) => <RecentRuns project={code} pipeline={c.row.original} /> }),
          ]}
        /></LegendView>
      </Card>
      {stalled.length ? (
        <Card>
          <CardHeader>
            <CardTitle>Scheduled but not running · {stalled.length}</CardTitle>
          </CardHeader>
          <DataTable find
            label="Scheduled but not running"
            data={stalled}
            columns={[
              link,
              schedule,
              columns.display({ id: "why", header: "Why", cell: (c) => (c.row.original.paused ? <PauseState pipeline={c.row.original} /> : <span className="text-warn">{c.row.original.schedule_problem ?? "No next run"}</span>) }),
            ]}
          />
        </Card>
      ) : null}
      <Card>
        <CardHeader><CardTitle>Run history by day</CardTitle></CardHeader>
        <div className="grid gap-3 p-4">
          <SelectField compact label="History pipeline" value={pipeline} onChange={value=>{const next=new URLSearchParams(params);if(value)next.set("pipeline",value);else next.delete("pipeline");setParams(next,{replace:true});}}>
            <option value="">All pipelines</option>
            {(list.data?.pipelines??[]).map(p=><option key={p.pipeline_code} value={p.pipeline_code}>{p.pipeline_code}</option>)}
          </SelectField>
          <p className="m-0 text-xs text-muted">Historical outcomes, including manual runs; this is not a forecast. Showing {history.all.length} loaded runs.</p>
          {history.runs.isPending?<Loading what="run history"/>:history.runs.isError?<Notice>{history.runs.error.message}</Notice>:<RunCalendar runs={history.all}/>}
          {history.runs.hasNextPage?<Button disabled={history.runs.isFetchingNextPage} onClick={()=>void history.runs.fetchNextPage()}>{history.runs.isFetchingNextPage?"Loading earlier runs…":"Load earlier runs"}</Button>:null}
        </div>
      </Card>
    </div>
  );
}
