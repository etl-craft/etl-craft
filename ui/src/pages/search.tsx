import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Loading, Notice, PageHeader } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { getJson, project } from "@/lib/api";
import { readRecent } from "@/lib/recent";
import { catalogPath, pipelinePath, runPath, taskPath } from "@/lib/routes";
import type { SearchHit, SearchView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<SearchHit>();

/** The page a hit opens: tables are in the generated catalog, everything else in the interface. */
function hitLink(code: string, hit: SearchHit): { to: string } {
  const pipeline = hit.pipeline_code ?? "";
  if (hit.kind === "TABLE") return { to: catalogPath(code, "tables", hit.label) };
  if (hit.kind === "RUN" && hit.run_id !== null) return { to: runPath(code, pipeline, hit.run_id) };
  if (hit.kind === "TASK") return { to: taskPath(code, pipeline, hit.label) };
  return { to: pipelinePath(code, pipeline) };
}

export function Search() {
  const { project: code = "" } = useParams();
  const [params] = useSearchParams();
  const q = params.get("q") ?? "";
  useDocumentTitle("Search", code);
  const found = useQuery({ queryKey: ["search", code, q], queryFn: () => getJson<SearchView>(`${project(code)}/search`, { q }), enabled: q.length > 0 });
  const recent = readRecent(code);
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Search" subtitle={`${code} · press / or Ctrl+K on any page`} />
      {found.isError ? <Notice>{(found.error as Error).message}</Notice> : null}
      {found.isFetching ? <Loading what="results" /> : null}
      {q === "" ? <p className="m-0 text-sm text-muted">Type part of a pipeline, task or table name, or an exact run id or run key, in the search box above.</p> : null}
      {found.data ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {found.data.hits.length} result{found.data.hits.length === 1 ? "" : "s"} for “{found.data.q}”
            </CardTitle>
            {found.data.truncated ? <span className="text-xs text-muted">More matched; type more of the name.</span> : null}
          </CardHeader>
          <DataTable
            label="Search results"
            data={found.data.hits}
            empty="Nothing you can see matches. Names match on any part; run ids and run keys match exactly. Tables are listed only with whole-project view."
            columns={[
              columns.accessor("kind", { header: "Kind", cell: (c) => c.getValue().toLowerCase() }),
              columns.accessor("label", {
                header: "Name",
                cell: (c) => {
                  const target = hitLink(code, c.row.original);
                  return (
                    <Link className="font-medium text-accent hover:underline" to={target.to}>
                      {c.getValue()}
                    </Link>
                  );
                },
              }),
              columns.accessor("pipeline_code", { header: "Pipeline", cell: (c) => c.getValue() ?? "" }),
              columns.accessor("detail", { header: "Detail" }),
            ]}
          />
        </Card>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>Recently viewed in this browser</CardTitle>
        </CardHeader>
        {recent.length ? (
          <ul className="m-0 grid list-none gap-1 p-4 text-sm">
            {recent.map((r) => (
              <li key={r.path}>
                <Link className="text-accent hover:underline" to={r.path}>
                  {r.label}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 p-4 text-sm text-muted">Pipelines and runs you open appear here.</p>
        )}
      </Card>
    </div>
  );
}
