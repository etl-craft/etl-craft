import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { AttemptDetails } from "@/components/attempt-details";
import { Breadcrumbs, Loading, Notice, PageHeader } from "@/components/common";
import { Card } from "@/components/ui/card";
import { useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { pipelinePath, pipelinesPath, runPath, taskPath } from "@/lib/routes";
import type { AttemptView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

export function Attempt() {
  const { project: code = "", pipeline = "", runId = "", task = "", attemptId = "" } = useParams();
  const info = useProjectInfo(code);
  const live = new Set(["QUEUED", "CLAIMED", "RUNNING"]);
  const found = useQuery({
    queryKey: ["attempt", code, attemptId],
    queryFn: () => getJson<AttemptView>(`${project(code)}/attempts/${attemptId}`),
    refetchInterval: (query) => (query.state.data && live.has(query.state.data.status) ? 3_000 : false),
  });
  useDocumentTitle(`Attempt ${found.data?.attempt_number ?? ""} · ${task} · run ${runId}`, code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const a = found.data;
  // Only an attempt of the run in the address is shown; any other pairing is not found, as for runs.
  const mismatch = a && String(a.pipeline_run_id) !== runId;
  return (
    <div className="grid grid-cols-1 gap-5">
      <Breadcrumbs
        trail={[
          { label: "Pipelines", to: pipelinesPath(code) },
          { label: pipeline, to: pipelinePath(code, pipeline) },
          { label: `Run ${runId}`, to: runPath(code, pipeline, runId) },
          { label: task, to: taskPath(code, pipeline, task) },
          { label: `Attempt ${attemptId}` },
        ]}
      />
      <PageHeader
        title={`Attempt ${a?.attempt_number ?? ""} of ${task}`}
        subtitle={
          <>
            <Link className="text-accent hover:underline" to={taskPath(code, pipeline, task)}>
              Task history
            </Link>{" "}
            · attempt id {attemptId}
          </>
        }
      />
      {found.isError ? <Notice>{(found.error as Error).message}</Notice> : null}
      {found.isPending ? <Loading what="the attempt" /> : null}
      {mismatch ? <Notice>Attempt {attemptId} belongs to run {a?.pipeline_run_id}, not run {runId}; open it from its own run.</Notice> : null}
      {a && !mismatch ? (
        <Card className="p-4">
          <AttemptDetails code={code} attempt={a} heading="Recorded outcome" showLog />
        </Card>
      ) : null}
    </div>
  );
}
