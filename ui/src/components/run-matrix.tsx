import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Loading, Notice } from "@/components/common";
import { StatusMark } from "@/components/status";
import { Table, Td, Th } from "@/components/ui/table";
import { getJson, project } from "@/lib/api";
import { runPath, taskPath } from "@/lib/routes";
import type { Graph, RunView, TaskHistory } from "@/lib/types";

/** Every task against the pipeline's recent runs: one glance shows where and when it started failing. */
export function RunMatrix({ code, pipeline, graph, runs }: { code: string; pipeline: string; graph: Graph; runs: RunView[] }) {
  const tasks = graph.waves.flat();
  const shown = runs.slice(0, 25);
  const newest = shown[0]?.pipeline_run_id;
  const cells = useQueries({
    queries: tasks.map((task) => ({
      queryKey: ["matrix", code, pipeline, task, newest, shown.length],
      enabled: newest !== undefined,
      queryFn: () => getJson<TaskHistory>(`${project(code)}/history`, { pipeline_code: pipeline, task_code: task, all: true, limit: shown.length, before: (newest ?? 0) + 1 }),
    })),
  });
  if (shown.length === 0) return <p className="m-0 p-4 text-muted">No runs yet.</p>;
  const failed = cells.find((c) => c.isError);
  return (
    <>
      {failed?.error ? <Notice className="m-4">{(failed.error as Error).message}</Notice> : null}
      {cells.some((c) => c.isPending) ? <Loading what="the matrix" className="p-4" /> : null}
      <Table aria-label="Run matrix">
        <thead>
          <tr>
            <Th className="sticky left-0 bg-surface-2">Task</Th>
            {shown.map((run) => (
              <Th key={run.pipeline_run_id} className="w-14 text-center">
                <Link className="num text-accent hover:underline" to={runPath(code, pipeline, run.pipeline_run_id)}>
                  #{run.pipeline_run_id}
                </Link>
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task, row) => (
            <tr key={task}>
              <Td className="sticky left-0 bg-surface font-medium">
                <Link className="text-accent hover:underline" to={taskPath(code, pipeline, task)}>
                  {task}
                </Link>
              </Td>
              {shown.map((run) => {
                const entry = cells[row]?.data?.entries.find((e) => e.pipeline_run_id === run.pipeline_run_id);
                return (
                  <Td key={run.pipeline_run_id} className="text-center">
                    {entry ? (
                      <Link to={runPath(code, pipeline, run.pipeline_run_id)} className="inline-grid">
                        <StatusMark status={entry.status} label={`${task} in run ${run.pipeline_run_id}: ${entry.status.toLowerCase()}`} />
                      </Link>
                    ) : (
                      <span className="text-muted" aria-label={`${task} did not start in run ${run.pipeline_run_id}`}>
                        ·
                      </span>
                    )}
                  </Td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}
