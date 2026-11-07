import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { Loading, Notice, PageHeader } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { PauseState, RecentRuns } from "@/components/pipeline-parts";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectInfo, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatTime, relative } from "@/lib/format";
import { pipelinePath } from "@/lib/routes";
import type { Pipeline } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<Pipeline>();

export function Scheduled() {
  const { project: code = "" } = useParams();
  const tz = useTimezone();
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
      <Link className="font-medium text-accent hover:underline" to={pipelinePath(code, c.getValue())}>
        {c.getValue()}
      </Link>
    ),
  });
  const schedule = columns.accessor("run_schedule", { header: "Schedule", enableSorting: false, cell: (c) => <code className="whitespace-nowrap font-mono text-xs">{c.getValue()}</code> });
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Scheduled runs" subtitle={`${code} · what runs next`} />
      {list.isError ? <Notice>{(list.error as Error).message}</Notice> : null}
      {list.isPending ? <Loading what="schedules" /> : null}
      <Card>
        <CardHeader>
          <CardTitle>Next runs · {upcoming.length}</CardTitle>
        </CardHeader>
        <DataTable
          label="Next runs"
          data={upcoming}
          empty={list.isSuccess ? "No scheduled pipeline has a next run." : undefined}
          columns={[
            columns.accessor("next_run", { header: "Next run", enableSorting: false, cell: (c) => <span className="num whitespace-nowrap"><span className="font-medium">{relative(c.getValue(), now)}</span> <span className="text-muted">{formatTime(c.getValue(), tz)}</span></span> }),
            link,
            schedule,
            columns.display({ id: "recent", header: "Recent runs", cell: (c) => <RecentRuns project={code} pipeline={c.row.original} /> }),
          ]}
        />
      </Card>
      {stalled.length ? (
        <Card>
          <CardHeader>
            <CardTitle>Scheduled but not running · {stalled.length}</CardTitle>
          </CardHeader>
          <DataTable
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
    </div>
  );
}
