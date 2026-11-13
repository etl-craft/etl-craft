import { ExternalLink } from "lucide-react";
import { Fact, FactList, Loading, Notice, PageHeader } from "@/components/common";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useAbout } from "@/hooks";
import { useDocumentTitle } from "@/title";

export function About() {
  useDocumentTitle("About");
  const about = useAbout();
  const data = about.data;
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="About etl-craft" />
      {about.isError ? <Notice>{(about.error as Error).message}</Notice> : null}
      {about.isPending ? <Loading what="versions" /> : null}
      {data ? (
        <>
          <Card className="p-4">
            <FactList>
              <Fact label="Package version">{data.package_version}</Fact>
              <Fact label="Engine DB schema version">{data.schema_version ?? "Not recorded"}</Fact>
              <Fact label="Server version">{data.server_version}</Fact>
              <Fact label="License">{data.license}</Fact>
            </FactList>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Live controllers</CardTitle>
            </CardHeader>
            <ul className="m-0 list-none p-4 text-sm">
              {data.controllers.map((c) => (
                <li key={c.controller_id}>
                  Controller {c.controller_id}: {c.version}
                </li>
              ))}
              {data.controllers.length ? null : <li className="text-muted">No live controller heartbeat. Ask the operator to start a controller.</li>}
            </ul>
          </Card>
          <a className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline" href={data.docs_url} target="_blank" rel="noopener noreferrer">
            Documentation for this release line <ExternalLink className="size-3.5" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        </>
      ) : null}
    </div>
  );
}
