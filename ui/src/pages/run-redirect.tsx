import { Navigate, useParams } from "react-router-dom";
import { runPath } from "@/lib/routes";

/** An older address of a run opens the run in its pipeline's workspace. */
export function RunRedirect() {
  const { project = "", pipeline = "", runId = "" } = useParams();
  return <Navigate replace to={runPath(project, pipeline, runId)} />;
}
