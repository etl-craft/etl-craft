import { Navigate, useLocation, useParams } from "react-router-dom";
import { pipelinePath } from "@/lib/routes";

/** An older run address opens its pipeline workspace with the same selection and filters. */
export function RunRedirect() {
  const { project = "", pipeline = "", runId = "" } = useParams();
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  params.set("run", runId);
  return <Navigate replace to={`${pipelinePath(project, pipeline)}?${params}`} />;
}
