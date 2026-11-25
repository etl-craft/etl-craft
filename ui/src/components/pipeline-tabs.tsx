import { AlertDeliveries } from "@/components/alert-deliveries";
import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import * as React from "react";
import { AppLink as Link } from "@/components/navigation";
import { EmptyState, Loading, Notice, SelectField } from "@/components/common";
import { columnsOf, DataTable } from "@/components/data-table";
import { getJson, project } from "@/lib/api";
import { formatSeconds } from "@/lib/format";
import { catalogPath, pipelinePath, scheduledPath } from "@/lib/routes";
import type { AuditRecords, Pipeline, RunView } from "@/lib/types";

const PIPELINE_TABS = [{id:"overview",label:"Overview"},{id:"runs",label:"Runs"},{id:"audit",label:"Audit log"},{id:"access",label:"Access"}];

/** The pipeline's own tabs, shown while no run or task is selected. */
export function pipelineTabs() {
  return PIPELINE_TABS;
}

const WINDOWS: Record<string, { label: string; hours: number }> = {
  "24h": { label: "Last 24 hours", hours: 24 },
  "7d": { label: "Last 7 days", hours: 24 * 7 },
  "30d": { label: "Last 30 days", hours: 24 * 30 },
};

const seconds = (run: RunView) => (run.start_date && run.end_date ? (new Date(run.end_date).getTime() - new Date(run.start_date).getTime()) / 1000 : null);

function Tile({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "bad" }) {
  return (
    <div data-card className="grid gap-1 rounded-sm border border-border bg-surface p-3">
      <span className="text-xs text-muted">{label}</span>
      <span className={tone === "bad" ? "text-2xl font-semibold text-bad" : "text-2xl font-semibold"}>{value}</span>
    </div>
  );
}

/** The pipeline over a window: how many runs, how many failed, how long they took, with links to the canonical run history. */
export function OverviewTab({ code, pipeline, runs }: { code: string; pipeline: Pipeline; runs: RunView[] }) {
  const [window, setWindow] = React.useState("24h");
  const [now] = React.useState(() => Date.now());
  const since = now - WINDOWS[window]!.hours * 3_600_000;
  const inWindow = runs.filter((run) => run.start_date && new Date(run.start_date).getTime() >= since);
  const failed = inWindow.filter((run) => run.status === "FAILED" || run.status === "LOST");
  const done = inWindow.map(seconds).filter((s): s is number => s !== null).sort((a, b) => a - b);
  const median = done.length ? done[Math.floor(done.length / 2)]! : null;
  const finished = inWindow.filter((run) => run.end_date);
  const rate = finished.length ? Math.round((finished.filter((run) => run.status === "SUCCESS").length / finished.length) * 100) : null;
  return (
    <div className="grid gap-4">
      <SelectField compact label="Window" value={window} onChange={setWindow}>
        {Object.entries(WINDOWS).map(([id, w]) => (
          <option key={id} value={id}>
            {w.label}
          </option>
        ))}
      </SelectField>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Runs" value={inWindow.length} />
        <Tile label="Failed runs" value={failed.length} tone={failed.length ? "bad" : undefined} />
        <Tile label="Success rate" value={rate === null ? "—" : `${rate}%`} />
        <Tile label="Median duration" value={median === null ? "—" : formatSeconds(median)} />
      </div>
      <AlertDeliveries code={code} rows={pipeline.alert_deliveries} />
      <p className="m-0 text-[13px] text-muted">
        <Link className="text-accent hover:underline" to={pipelinePath(code,pipeline.pipeline_code,"runs")}>Open run history</Link>
        {" · "}<Link className="text-accent hover:underline" to={scheduledPath(code,pipeline.pipeline_code)}>Run history by day</Link>
        {" · "}<Link className="text-accent hover:underline" to={catalogPath(code,"pipelines",pipeline.pipeline_code)}>About this pipeline in the catalog</Link>
      </p>
    </div>
  );
}

/** What was done to this pipeline: the commands run on it and the metadata changes to it. */
export function AuditTab({ code, pipeline }: { code: string; pipeline: string }) {
  const audit = useQuery({ queryKey: ["audit", code, pipeline], queryFn: () => getJson<AuditRecords>(`${project(code)}/audit`, { pipeline_code: pipeline }) });
  if (audit.isError) return <Notice>{(audit.error as Error).message}</Notice>;
  if (!audit.data) return <Loading what="the audit log" />;
  const { actions } = audit.data;
  // Many edits made together (a config apply) are one line with a count, not one line each.
  const grouped = new Map<string, { change: (typeof audit.data.changes)[number]; count: number }>();
  for (const c of audit.data.changes) {
    const key = `${c.at.slice(0, 16)}|${c.actor}|${c.table_name}|${c.operation}`;
    const found = grouped.get(key);
    if (found) found.count += 1;
    else grouped.set(key, { change: c, count: 1 });
  }
  const changes = [...grouped.values()];
  return (
    <div className="grid gap-4">
      <section className="grid gap-2" aria-label="Commands">
        <h3 className="m-0 text-sm font-semibold">Commands ({actions.length})</h3>
        {actions.length ? (
          <DataTable
            label="Commands run on this pipeline"
            data={actions.slice(0, 50)}
            columns={columnsOf<(typeof actions)[number]>([
              { id: "when", header: "When", value: (a) => a.at, size: 200, cell: (a) => <When iso={a.at} /> },
              { id: "who", header: "Who", value: (a) => a.actor, size: 160 },
              { id: "command", header: "Command", value: (a) => a.command, size: 320 },
              { id: "outcome", header: "Outcome", value: (a) => a.outcome, size: 140, cell: (a) => <span className="text-muted">{a.outcome.toLowerCase()}</span> },
            ])}
          />
        ) : (
          <EmptyState title="No command has been recorded for this pipeline." nextStep="Use a pipeline action to record a request in this list." />
        )}
      </section>
      <section className="grid gap-2" aria-label="Metadata changes">
        <h3 className="m-0 text-sm font-semibold">Metadata changes ({audit.data.changes.length})</h3>
        {changes.length ? (
          <DataTable
            label="Metadata changes"
            data={changes.slice(0, 50)}
            columns={columnsOf<(typeof changes)[number]>([
              { id: "when", header: "When", value: (g) => g.change.at, size: 200, cell: (g) => <When iso={g.change.at} /> },
              { id: "who", header: "Who", value: (g) => g.change.actor, size: 160 },
              { id: "table", header: "Table", value: (g) => g.change.table_name, size: 280, cell: (g) => <span className="font-mono text-xs">{g.change.table_name}</span> },
              { id: "change", header: "Change", value: (g) => g.change.operation, size: 140, cell: (g) => <span className="text-muted">{g.change.operation.toLowerCase()}</span> },
              { id: "count", header: "Rows", value: (g) => g.count, size: 90 },
            ])}
          />
        ) : (
          <EmptyState title="No metadata change has been recorded for this pipeline." nextStep="Apply changes through the project config files to record their history." />
        )}
      </section>
    </div>
  );
}
