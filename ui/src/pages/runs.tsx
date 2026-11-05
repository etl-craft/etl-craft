import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { PageHeader, SelectField } from "@/components/common";
import { RunsTable } from "@/components/runs-table";
import { Button } from "@/components/ui/button";
import { useProjectInfo } from "@/hooks";
import { getJson, project } from "@/lib/api";
import type { Pipeline } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const STATUSES = ["FAILED", "IN-PROGRESS", "SUCCESS", "SKIPPED", "LOST"];

export function Runs() {
  const { project: code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const pipeline = params.get("pipeline") ?? "";
  const status = params.get("status") ?? "";
  const info = useProjectInfo(code);
  useDocumentTitle("Runs", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const pipelines = useQuery({ queryKey: ["pipelines", code], queryFn: () => getJson<{ pipelines: Pipeline[] }>(`${project(code)}/pipelines`) });

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader
        title="Pipeline runs"
        subtitle={code}
        actions={
          <div className="flex flex-wrap items-end gap-3">
            <SelectField compact label="Pipeline" value={pipeline} onChange={(value) => set("pipeline", value)}>
              <option value="">All pipelines</option>
              {(pipelines.data?.pipelines ?? []).map((p) => (
                <option key={p.pipeline_code} value={p.pipeline_code}>
                  {p.pipeline_code}
                </option>
              ))}
            </SelectField>
            <SelectField compact label="Status" value={status} onChange={(value) => set("status", value)}>
              <option value="">Any status</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s === "IN-PROGRESS" ? "Running" : s.charAt(0) + s.slice(1).toLowerCase()}
                </option>
              ))}
            </SelectField>
            {pipeline || status ? (
              <Button variant="ghost" onClick={() => setParams({}, { replace: true })}>
                Clear filters
              </Button>
            ) : null}
          </div>
        }
      />
      <RunsTable code={code} pipeline={pipeline || undefined} status={status || undefined} />
    </div>
  );
}
