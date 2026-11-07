import { useQueries, useQuery } from "@tanstack/react-query";
import * as React from "react";
import { Link } from "react-router-dom";
import { Fact, FactList, Loading, Notice, SelectField } from "@/components/common";
import { RunBars } from "@/components/pipeline-parts";
import { StatusBadge } from "@/components/status";
import { Table, Td, Th } from "@/components/ui/table";
import { useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { taskPath } from "@/lib/routes";
import type { Graph, Pipeline, RunView, Steps, TaskDefinition } from "@/lib/types";

const WINDOWS: Record<string, { label: string; hours: number }> = {
  "24h": { label: "Last 24 hours", hours: 24 },
  "7d": { label: "Last 7 days", hours: 24 * 7 },
  "30d": { label: "Last 30 days", hours: 24 * 30 },
};

const seconds = (run: RunView) => (run.start_date && run.end_date ? (new Date(run.end_date).getTime() - new Date(run.start_date).getTime()) / 1000 : null);

function Tile({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "bad" }) {
  return (
    <div className="grid gap-1 rounded-lg border border-border bg-surface p-3">
      <span className="text-xs text-muted">{label}</span>
      <span className={tone === "bad" ? "text-2xl font-semibold text-bad" : "text-2xl font-semibold"}>{value}</span>
    </div>
  );
}

/** The pipeline over a window: how many runs, how many failed, how long they took, and the newest durations. */
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
        <Tile label="Median duration" value={median === null ? "—" : formatDuration("1970-01-01T00:00:00Z", new Date(median * 1000).toISOString())} />
      </div>
      <section className="grid gap-2" aria-label="Latest run durations">
        <h3 className="m-0 text-sm font-semibold">Last {Math.min(10, runs.length)} runs</h3>
        {runs.length ? <RunBars project={code} runs={runs.slice(0, 10)} /> : <p className="m-0 text-muted">No runs yet.</p>}
      </section>
      <section className="grid gap-2" aria-label="Recent failures">
        <h3 className="m-0 text-sm font-semibold">Recent failures</h3>
        {failed.length === 0 ? (
          <p className="m-0 text-muted">No failed runs in this window.</p>
        ) : (
          <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
            {failed.slice(0, 8).map((run) => (
              <li key={run.pipeline_run_id} className="flex flex-wrap items-center gap-2">
                <StatusBadge status={run.status} />
                <Link className="num text-accent hover:underline" to={`/projects/${encodeURIComponent(code)}/pipelines/${encodeURIComponent(pipeline.pipeline_code)}?run=${run.pipeline_run_id}`}>
                  #{run.pipeline_run_id}
                </Link>
                <span className="text-muted">{formatDuration(run.start_date, run.end_date)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Each task's definition, read once and shared by the tabs that list tasks. */
export function useTaskDefinitions(code: string, pipeline: string, tasks: string[]) {
  const results = useQueries({
    queries: tasks.map((task) => ({
      queryKey: ["task", code, pipeline, task],
      queryFn: () => getJson<TaskDefinition>(`${project(code)}/task`, { pipeline_code: pipeline, task_code: task }),
      staleTime: 60_000,
    })),
  });
  return { definitions: new Map(tasks.map((task, i) => [task, results[i]?.data])), loading: results.some((r) => r.isPending), error: results.find((r) => r.isError)?.error as Error | undefined };
}

/** Every task of the pipeline with its handler, what it waits for, and its state in the selected run. */
export function TasksTab({ code, pipeline, graph, runId }: { code: string; pipeline: string; graph: Graph; runId?: number }) {
  const tasks = graph.waves.flat();
  const { definitions, loading, error } = useTaskDefinitions(code, pipeline, tasks);
  const steps = useQuery({
    queryKey: ["steps", code, pipeline, runId],
    queryFn: () => getJson<Steps>(`${project(code)}/steps`, { pipeline_code: pipeline, run_id: runId }),
    enabled: runId !== undefined,
  });
  const status = new Map((steps.data?.steps ?? []).map((s) => [s.task_code, s.status ?? "QUEUED"]));
  return (
    <div className="grid gap-3">
      {error ? <Notice>{error.message}</Notice> : null}
      {loading ? <Loading what="tasks" /> : null}
      <div className="overflow-hidden rounded-lg border border-border">
        <Table aria-label="Pipeline tasks">
          <thead>
            <tr>
              <Th>Task</Th>
              <Th>Handler</Th>
              <Th>Waits for</Th>
              {runId !== undefined ? <Th>{`Run #${runId}`}</Th> : null}
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task}>
                <Td>
                  <Link className="font-medium text-accent hover:underline" to={taskPath(code, pipeline, task)}>
                    {task}
                  </Link>
                </Td>
                <Td>{definitions.get(task)?.handler ?? "…"}</Td>
                <Td className="text-muted">{(graph.depends_on[task] ?? []).map(([upstream]) => upstream).join(", ") || "—"}</Td>
                {runId !== undefined ? <Td>{status.has(task) ? <StatusBadge status={status.get(task)!} /> : "—"}</Td> : null}
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </div>
  );
}

/** The pipeline's definition as the project's files set it. */
export function DetailsTab({ pipeline, graph, project: code }: { pipeline: Pipeline; graph?: Graph; project: string }) {
  const tz = useTimezone();
  return (
    <FactList className="sm:grid-cols-2 lg:grid-cols-2">
      <Fact label="Pipeline">{pipeline.pipeline_code}</Fact>
      <Fact label="Name">{pipeline.pipeline_name}</Fact>
      <Fact label="Project">{code}</Fact>
      <Fact label="Refresh">{pipeline.refresh_type.toLowerCase()}</Fact>
      <Fact label="Schedule">{pipeline.run_schedule ? <code className="font-mono">{pipeline.run_schedule}</code> : "Not scheduled"}</Fact>
      <Fact label="Restarts">{pipeline.restart_note ?? "On its schedule only"}</Fact>
      <Fact label="Next run">{pipeline.next_run ? formatTime(pipeline.next_run, tz) : (pipeline.schedule_problem ?? "—")}</Fact>
      <Fact label="SLA">{pipeline.sla_in_hours ? `${pipeline.sla_in_hours} h` : "None"}</Fact>
      <Fact label="Automatic runs">{pipeline.paused ? `Paused by ${pipeline.paused.paused_by}: ${pipeline.paused.reason}` : "On"}</Fact>
      <Fact label="Tasks">{graph ? graph.waves.flat().length : "…"}</Fact>
      <Fact label="Tags">{pipeline.tags.length ? pipeline.tags.join(", ") : "None"}</Fact>
    </FactList>
  );
}

/** What the pipeline does, then what each task does, from `DESCRIPTION` and each task's `DOCUMENTATION`. */
export function DocsTab({ code, pipeline, graph }: { code: string; pipeline: Pipeline; graph: Graph }) {
  const tasks = graph.waves.flat();
  const { definitions, loading, error } = useTaskDefinitions(code, pipeline.pipeline_code, tasks);
  return (
    <div className="grid gap-4">
      <section className="grid gap-1" aria-label="About this pipeline">
        <h3 className="m-0 text-sm font-semibold">About this pipeline</h3>
        <p className="m-0 whitespace-pre-wrap text-[13px]">{pipeline.description || <span className="text-muted">No description. Set DESCRIPTION on the pipeline.</span>}</p>
      </section>
      {error ? <Notice>{error.message}</Notice> : null}
      {loading ? <Loading what="task documentation" /> : null}
      <section className="grid gap-3" aria-label="Task documentation">
        <h3 className="m-0 text-sm font-semibold">Tasks</h3>
        {tasks.map((task) => {
          const text = definitions.get(task)?.parameters.DOCUMENTATION;
          return (
            <div key={task} className="grid gap-0.5 border-l-2 border-border pl-3">
              <Link className="w-fit font-medium text-accent hover:underline" to={taskPath(code, pipeline.pipeline_code, task)}>
                {task}
              </Link>
              <p className="m-0 whitespace-pre-wrap text-[13px]">{text || <span className="text-muted">No documentation. Set the task's DOCUMENTATION parameter.</span>}</p>
            </div>
          );
        })}
      </section>
    </div>
  );
}
