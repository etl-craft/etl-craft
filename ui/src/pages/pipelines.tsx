import { PipelinePause } from "@/components/pipeline-pause";
import {LegendView,statusEntries} from "@/components/legend";
import { AutoStartNotice } from "@/components/auto-start-notice";
import { RunLabel } from "@/components/run-label";
import { When } from "@/components/when";
import { TagFilter } from "@/components/tag-filter";
import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Pause, Play } from "lucide-react";
import * as React from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { AppLink as Link } from "@/components/navigation";
import { ActionButton } from "@/components/action-button";
import { EmptyState, Loading, Notice, PageHeader } from "@/components/common";
import { CsvButton } from "@/components/csv-button";
import { DataTable } from "@/components/data-table";
import { NextRun, PauseState, RecentRuns, TagList } from "@/components/pipeline-parts";
import { slaVerdict, StatusBadge } from "@/components/status";
import { Card } from "@/components/ui/card";
import { unavailableAction, useActionAvailability, useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { pipelinePath, runPath } from "@/lib/routes";
import { BulkRefresh, PipelineRefresh } from "@/components/pipeline-refresh";
import type { BulkOutcome, Pipeline } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<Pipeline>();

export const describeOutcomes = (result: { outcomes: BulkOutcome[] }): string => {
  const refused = result.outcomes.filter((o) => o.error);
  const done = result.outcomes.length - refused.length;
  return `${done} requested${refused.length ? `; ${refused.length} refused: ${refused.map((o) => `${o.pipeline_code} (${o.error})`).join("; ")}` : ""}.`;
};

export function Pipelines() {
  const { project: code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tags = params.getAll("tag");
  const text = params.get("q") ?? "";
  const info = useProjectInfo(code);
  useDocumentTitle("Pipelines", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const list = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`), refetchInterval: 15_000 });
  const all = React.useMemo(() => list.data?.pipelines ?? [], [list.data]);
  const known = React.useMemo(() => [...new Set(all.flatMap((p) => p.tags))].sort(), [all]);
  const shown = React.useMemo(() => all.filter((p) => tags.every((t) => p.tags.includes(t)) && (!text || `${p.pipeline_code} ${p.pipeline_name} ${p.description ?? ""}`.toLowerCase().includes(text.toLowerCase()))), [all, tags, text]);
  const [chosen, setChosen] = React.useState<ReadonlySet<string>>(new Set());
  const selected = shown.filter((p) => chosen.has(p.pipeline_code)).map((p) => p.pipeline_code);
  const bulkAvailability = useActionAvailability(code, undefined, !!selected.length, { pipeline_codes: selected });

  const toggleTag = (tag: string) => {
    const next = new URLSearchParams(window.location.search);
    const now = next.getAll("tag");
    next.delete("tag");
    (now.includes(tag) ? now.filter((t) => t !== tag) : [...now, tag]).forEach((t) => next.append("tag", t));
    setParams(next, { replace: true });
  };
  const find = (value: string) => {
    const next = new URLSearchParams(window.location.search);
    if (value) next.set("q", value);
    else next.delete("q");
    setParams(next, { replace: true });
  };
  const bulk = (action: "PAUSE" | "RESUME", verb: string) => (
    <ActionButton<{ outcomes: BulkOutcome[] }>
      code={code}
      label={`${verb} selected`}
      title={`${verb} ${selected.length} pipeline${selected.length === 1 ? "" : "s"}`}
      effect={`${action === "PAUSE" ? "Stops new automatic runs of" : "Allows automatic runs of"}: ${selected.join(", ")}. Each pipeline succeeds or is refused on its own.`}
      endpoint="/controls/bulk"
      unavailableReason={selected.length ? unavailableAction(bulkAvailability, "/controls/bulk", "POST", { action }) : "Select pipelines first."}
      body={(reason) => ({ requests: selected.map((pipeline_code) => ({ pipeline_code, action, reason })) })}
      describe={describeOutcomes}
      icon={action === "PAUSE" ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
      size="sm"
    />
  );

  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader
        title="Pipelines"
        subtitle={tags.length ? `Tagged ${tags.join(" and ")}` : undefined}
        actions={
          <div className="flex flex-wrap items-start gap-2">
          <PipelineRefresh code={code} onDone={() => void list.refetch()} />
          <CsvButton
            name={`${code}-pipelines.csv`}
            header={["pipeline", "name", "description", "tags", "schedule", "dependencies", "last_run", "next_run", "automatic_runs", "paused_tasks"]}
            rows={(selected.length ? shown.filter((p) => chosen.has(p.pipeline_code)) : shown).map((p) => [
              p.pipeline_code, p.pipeline_name, p.description ?? "", p.tags.join(" "), p.run_schedule ?? "", p.depends_on.map(([name, kind]) => `${name} (${kind})`).join(", "), p.recent_runs[0]?.pipeline_run_id ?? "", p.next_run ?? "", p.paused ? `paused by ${p.paused.paused_by}: ${p.paused.reason}` : "active", p.task_pauses.length,
            ])}
          />
          </div>
        }
      />
      <AutoStartNotice code={code} />
      <div className="flex flex-wrap items-center gap-3">
        <input type="search" aria-label="Find a pipeline" value={text} onChange={(event) => find(event.target.value)} placeholder="Find by name or description" className="h-control w-72 rounded-md border border-border-strong bg-surface px-3 text-sm" />
        <TagFilter known={known} selected={tags} onToggle={toggleTag} onClear={() => setParams(new URLSearchParams(), { replace: true })} />
        <span className="text-xs text-muted">{shown.length} of {all.length} pipelines</span>
      </div>
      {list.isError ? <Notice>{(list.error as Error).message}</Notice> : null}
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
          <span className="text-sm font-medium">{selected.length} selected</span>
          {bulk("PAUSE", "Pause")}
          {bulk("RESUME", "Resume")}
          <BulkRefresh code={code} pipelines={selected} />
        </div>
        <LegendView entries={statusEntries(shown.flatMap(pipeline=>pipeline.recent_runs.map(run=>run.status)))}><DataTable
          label="Pipelines"
          data={shown}
          empty={list.isSuccess ? (tags.length ? <EmptyState title="No pipeline carries every selected tag." nextStep="Clear a tag to broaden the list." /> : <EmptyState title="This project has no active pipeline." nextStep="Add a pipeline in the project config files, apply them, then refresh the pipeline definitions." />) : undefined}
          rowId={(p) => p.pipeline_code}
          selection={{
            ids: chosen,
            onToggle: (id) => setChosen((now) => (now.has(id) ? new Set([...now].filter((x) => x !== id)) : new Set([...now, id]))),
            onToggleAll: (every) => setChosen(every ? new Set(shown.map((p) => p.pipeline_code)) : new Set()),
          }}
          initialSort={[{ id: "pipeline", desc: false }]}
          columns={[
            columns.accessor("pipeline_code", {
              id: "pipeline",
              header: "Pipeline",
              cell: (c) => (
                <span className="grid">
                  <Link className="font-medium text-fg hover:text-accent hover:underline" to={pipelinePath(code, c.getValue())}>
                    {c.getValue()}
                  </Link>
                  {c.row.original.pipeline_name !== c.getValue() ? <span className="text-xs text-muted">{c.row.original.pipeline_name}</span> : null}
                </span>
              ),
            }),
            columns.display({ id: "recent", header: "Recent success", minSize: 176, cell: (c) => <RecentRuns project={code} pipeline={c.row.original} /> }),
            columns.display({ id: "description", header: "Description", cell: (c) => <span className="line-clamp-2 max-w-md text-[13px] text-muted" title={c.row.original.description ?? undefined}>{c.row.original.description ?? "—"}</span> }),
            columns.display({ id: "tags", header: "Tags", cell: (c) => <TagList tags={c.row.original.tags} /> }),
            columns.accessor("run_schedule", { header: "Schedule", enableSorting: false, cell: (c) => (c.getValue() ? <code className="whitespace-nowrap font-mono text-xs">{c.getValue()}</code> : <span className="whitespace-nowrap text-muted">Not scheduled</span>) }),
            columns.display({ id: "dependencies", header: "Waits for", cell: (c) => c.row.original.depends_on.length ? c.row.original.depends_on.map(([pipeline, kind]) => `${pipeline} (${kind})`).join(", ") : "None" }),
            columns.display({ id: "last", header: "Last run", cell: (c) => {
              const pipeline = c.row.original;
              const run = pipeline.recent_runs[0];
              return run ? <span className="grid gap-1"><RunLabel id={run.pipeline_run_id} label={run.run_label} to={runPath(code, pipeline.pipeline_code, run.pipeline_run_id)} /><When iso={run.start_date} /></span> : <span className="text-muted">No runs yet</span>;
            } }),
            columns.display({ id: "next", header: "Next run", cell: (c) => <NextRun pipeline={c.row.original} /> }),
            ...(all.some((p) => p.sla_in_hours) ? [
            columns.display({
              id: "sla",
              header: "SLA",
              minSize: 112,
              cell: (c) => {
                const p = c.row.original;
                const newest = p.recent_runs[0];
                const latest = newest ? slaVerdict(newest) : null;
                return latest ? <StatusBadge status={latest} /> : <span className="text-muted">{!p.sla_in_hours ? "—" : newest ? "No verdict" : "No run yet"}</span>;
              },
            })
            ] : []),
            columns.display({ id: "auto", header: "Automatic runs", minSize:220, cell: (c) => <div className="flex flex-wrap items-center gap-2"><PauseState pipeline={c.row.original} /><PipelinePause code={code} pipeline={c.row.original}/></div> }),
          ]}
        /></LegendView>
        {list.isPending ? <Loading what="pipelines" className="p-4" /> : null}
      </Card>
    </div>
  );
}
