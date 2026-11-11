import { RunLabel } from "@/components/run-label";
import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import * as React from "react";
import { useParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { EmptyState, Breadcrumbs, Loading, Notice, PageHeader, SelectField } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { Card } from "@/components/ui/card";
import { useCanRun, useProjectInfo, useRunReference } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { pipelinesPath, pipelinePath, runPath, taskPath } from "@/lib/routes";
import type { ItemRecord, Items as ItemsView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<ItemRecord>();
const result = (r: { message?: string }) => r.message ?? "Request recorded.";

export function Items() {
  const { project: code = "", pipeline = "", runId = "", task = "" } = useParams();
  const addressed = useRunReference(code, runId);
  const canRun = useCanRun(code);
  const info = useProjectInfo(code);
  const [status, setStatus] = React.useState("SUCCESS");
  useDocumentTitle(`Items · ${task} · run ${runId}`, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const base = `/pipelines/${encodeURIComponent(pipeline)}/runs/${runId}/tasks/${encodeURIComponent(task)}/items`;
  const items = useQuery({ queryKey: ["items", code, pipeline, runId, task], queryFn: () => getJson<ItemsView>(project(code) + base), refetchInterval: 10_000 });
  const scope = `task ${task} in run ${runId}`;
  const progress = items.data?.progress;
  const act = (item: ItemRecord, action: "RERUN" | "CANCEL" | "MARK", effect: string) => (
    <ActionButton<{ message?: string }>
      code={code}
      label={action === "MARK" ? "Mark as" : action.charAt(0) + action.slice(1).toLowerCase()}
      title={`${action.charAt(0) + action.slice(1).toLowerCase()} item ${item.key}`}
      effect={`${effect} (item ${item.key} of ${scope})`}
      endpoint={`${base}/controls`}
      body={(reason) => ({ action, item_key: item.key, reason, ...(action === "MARK" ? { status } : {}) })}
      describe={result}
      fields={
        action === "MARK" ? (
          <SelectField label="Mark as" value={status} onChange={setStatus}>
            {["SUCCESS", "FAILED", "SKIPPED"].map((s) => <option key={s}>{s}</option>)}
          </SelectField>
        ) : undefined
      }
      size="sm"
    />
  );
  if (addressed.isError) return <Notice>{(addressed.error as Error).message}</Notice>;
  if (addressed.isPending) return <Loading what="the selected run" />;
  return (
    <div className="grid grid-cols-1 gap-5">
      <Breadcrumbs trail={[{ label: "Pipelines", to: pipelinesPath(code) }, { label: pipeline, to: pipelinePath(code, pipeline) }, { label: `Run ${addressed.data.pipeline_run_id} · ${addressed.data.run_label ?? ""}`, to: runPath(code, pipeline, addressed.data.pipeline_run_id) }, { label: task, to: taskPath(code, pipeline, task) }, { label: "Items" }]} />
      <PageHeader
        title={`Items of ${task}`}
        subtitle={progress ? `items ${progress.done} / ${progress.total}, ${progress.failed} failed, ${progress.skipped} skipped` : undefined}
        actions={
          canRun && progress?.failed ? (
            <ActionButton<{ message?: string }>
              code={code}
              label="Rerun failed items"
              title={`Rerun the ${progress.failed} failed items`}
              effect={`Runs every failed item of ${scope} again; items that succeeded are kept.`}
              endpoint={`${base}/controls`}
              body={(reason) => ({ action: "RERUN", all_failed: true, reason })}
              describe={result}
              variant="primary"
            />
          ) : null
        }
      />
      {items.isError ? <Notice>{(items.error as Error).message}</Notice> : null}
      {items.isPending ? <Loading what="items" /> : null}
      {items.data ? <RunLabel id={items.data.task_run_id} label={items.data.task_run_label} /> : null}
      <Card>
        <DataTable
          label="Items"
          data={items.data?.records ?? []}
          empty={items.isSuccess ? <EmptyState title="This task run recorded no items.">An ingestion task publishes items through its scripting helper.</EmptyState> : undefined}
          columns={[
            columns.accessor("key", { header: "Item", cell: (c) => <span className="font-mono text-xs">{c.getValue()}</span> }),
            columns.accessor("status", { header: "Status", cell: (c) => <StatusBadge status={c.getValue()} /> }),
            columns.accessor("row_count", { header: "Rows", cell: (c) => <span className="num">{c.getValue() ?? "Not measured"}</span> }),
            columns.accessor("started", { header: "Started", cell: (c) => <span className="num whitespace-nowrap">{c.getValue() ?? ""}</span> }),
            columns.accessor("ended", { header: "Ended", cell: (c) => <span className="num whitespace-nowrap">{c.getValue() ?? ""}</span> }),
            columns.accessor("error", { header: "Error", cell: (c) => <span className="break-words text-bad">{c.getValue() ?? ""}</span> }),
            ...(canRun
              ? [
                  columns.display({
                    id: "act",
                    header: "Actions",
                    cell: (c) => (
                      <span className="flex flex-wrap gap-1">
                        {act(c.row.original, "RERUN", "Runs this item again.")}
                        {act(c.row.original, "CANCEL", "Asks the running attempt to stop this item; acknowledged when execution ends.")}
                        {act(c.row.original, "MARK", "Records the chosen status for this item.")}
                      </span>
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
