import { useQuery } from "@tanstack/react-query";
import { Loading, Notice } from "@/components/common";
import { useRunReference } from "@/hooks";
import { getJson, project as apiProject } from "@/lib/api";
import type { TaskHistory } from "@/lib/types";
import { Navigate, useParams } from "react-router-dom";
import { pipelinePath } from "@/lib/routes";

/** An older task address opens the task's own panel: its definition, lookups, offsets, pauses and history. */
export function TaskRedirect() {
  const { project = "", pipeline = "", task = "" } = useParams();
  return <Navigate replace to={`${pipelinePath(project, pipeline)}?${new URLSearchParams({ task })}`} />;
}

export function AttemptRedirect() {
  const { project = "", pipeline = "", runId = "", task = "", attemptId = "" } = useParams();
  const run = useRunReference(project, runId);
  const id = run.data?.pipeline_run_id;
  const history = useQuery({
    queryKey: ["task-history", project, pipeline, id, task],
    queryFn: () => getJson<TaskHistory>(`${apiProject(project)}/history`, { pipeline_code: pipeline, run_id: id, task_code: task }),
    enabled: id !== undefined && run.data?.pipeline_code === pipeline,
    retry: false,
  });
  if (run.error || history.error) return <Notice>{run.error?.message ?? history.error?.message}</Notice>;
  if (run.data && run.data.pipeline_code !== pipeline) return <Notice>The run does not belong to this pipeline.</Notice>;
  if (run.isPending || history.isPending) return <Loading what="the attempt" />;
  const attempts = history.data?.entries[0]?.attempts ?? [];
  const attempt = attempts.find(item => String(item.attempt_id) === attemptId);
  if (!attempt) return <Notice>Attempt {attemptId} is not recorded for {task} in run #{id}.</Notice>;
  const params = new URLSearchParams({ run: String(id), task });
  if (attempt !== attempts.at(-1)) params.set("try", String(attempt.attempt_number));
  return <Navigate replace to={`${pipelinePath(project, pipeline)}?${params}`} />;
}
