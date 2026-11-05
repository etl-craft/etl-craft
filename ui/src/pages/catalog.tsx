import { useMutation, useQuery } from "@tanstack/react-query";
import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { Loading, Notice, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { failureText, useProjectInfo, useRoleAtLeast } from "@/hooks";
import { ApiError, getJson, getText, project } from "@/lib/api";
import { catalogSite } from "@/lib/routes";
import type { Report } from "@/lib/types";
import { useDocumentTitle } from "@/title";
import { useParams } from "react-router-dom";

type Done = { message?: string };

export function Catalog() {
  const { project: code = "" } = useParams();
  const developer = useRoleAtLeast("developer");
  const admin = useRoleAtLeast("admin");
  const info = useProjectInfo(code);
  useDocumentTitle("Catalog", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const [frame, setFrame] = React.useState(0);
  // The built site is the last build; a missing build is shown in place of the frame, with Rebuild still reachable.
  const built = useQuery({ queryKey: ["catalog-built", code, frame], queryFn: () => getText(`${project(code)}/catalog/page`, { path: "index.html" }).then(() => true), retry: false });
  const validate = useMutation({ mutationFn: () => getJson<Report>(`${project(code)}/validation`) });
  const report = validate.data;
  const rebuilt = () => setFrame((n) => n + 1);
  const missing = built.error instanceof ApiError ? built.error.message : null;

  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader
        title={`${code} catalog`}
        subtitle="Generated project catalog. It shows the last build; rebuild it after metadata changes."
        actions={
          <div className="flex flex-wrap items-start gap-2" role="group" aria-label="Catalog actions">
            <Button onClick={() => validate.mutate()} disabled={validate.isPending}>
              Validate metadata
            </Button>
            {developer ? (
              <>
                <ActionButton<Done> code={code} label="Rebuild catalog" title="Rebuild the catalog" effect="Generates the catalog again from the current metadata." endpoint="/docs" body={() => ({})} askReason={false} describe={(r) => r.message ?? "The catalog was rebuilt."} onDone={rebuilt} variant="primary" />
                <ActionButton<Done> code={code} label="Refresh lineage" title="Refresh lineage" effect="Works every task's lineage out again, then traces it." endpoint="/lineage/refresh" body={() => ({})} askReason={false} describe={(r) => r.message ?? "Lineage was refreshed."} onDone={rebuilt} />
              </>
            ) : null}
            {admin ? (
              <ActionButton<Done> code={code} label="Record catalog versions" title="Record catalog versions" effect="Records the current definitions as the published catalog versions." endpoint="/docs/versions" body={() => ({})} askReason={false} describe={() => "The catalog versions were recorded."} />
            ) : null}
          </div>
        }
      />
      {validate.isError ? <Notice>{failureText(validate.error)}</Notice> : null}
      {report ? (
        <Card>
          <CardHeader>
            <CardTitle>Validation</CardTitle>
            <span className="text-xs text-muted">
              Checked {report.pipelines} pipeline(s) and {report.tasks} task(s): {report.findings.length} finding(s)
            </span>
          </CardHeader>
          {report.findings.length ? (
            <ul className="m-0 grid list-none gap-1 p-4 text-[13px]">
              {report.findings.map((f, i) => (
                <li key={i} className="break-words">
                  {f.severity ? <span className="mr-2 font-medium">{f.severity}</span> : null}
                  {f.message}
                </li>
              ))}
            </ul>
          ) : (
            <p className="m-0 p-4 text-muted">The metadata is valid.</p>
          )}
        </Card>
      ) : null}
      {built.isPending ? <Loading what="the catalog" /> : null}
      {missing ? (
        <Notice info>
          {missing.replace(/[.\s]+$/, "")}.{developer ? " Use Rebuild catalog above." : ""}
        </Notice>
      ) : null}
      {built.isSuccess ? <iframe key={frame} title={`${code} generated catalog`} src={catalogSite(code)} className="h-[78vh] w-full rounded-lg border border-border bg-surface" /> : null}
    </div>
  );
}
