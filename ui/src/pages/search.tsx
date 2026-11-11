import { RunLabel } from "@/components/run-label";
import { searchDetail } from "@/lib/labels";
import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { EmptyState, Highlight, Loading, Notice, PageHeader, Pager } from "@/components/common";
import { useIdentity } from "@/hooks";
import { DataTable } from "@/components/data-table";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { getJson, project } from "@/lib/api";
import { readRecent } from "@/lib/recent";
import { catalogPath, pipelinePath, runPath, taskPath } from "@/lib/routes";
import type { SearchHit, SearchView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<SearchHit>();

/** The page a hit opens: tables are in the generated catalog, everything else in the interface. */
export function hitLink(code: string, hit: SearchHit): { to: string } {
  const pipeline = hit.pipeline_code ?? "";
  if (hit.kind === "TABLE") return { to: catalogPath(code, "tables", hit.label) };
  if (hit.kind === "RUN" && hit.run_id !== null) return { to: runPath(code, pipeline, hit.run_id) };
  if (hit.kind === "TASK") return { to: taskPath(code, pipeline, hit.label) };
  return { to: pipelinePath(code, pipeline) };
}

export function Search() {
  const { project: code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const kind = params.get("kind") ?? "ALL";
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const size = useIdentity().data?.settings.page_size ?? 25;
  const change = (patch: Record<string, string | null>) => {
    // Read the address, not the captured params: two changes in one event must both survive.
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
  };
  useDocumentTitle("Search", code);
  const found = useQuery({ queryKey: ["search", code, q], queryFn: () => getJson<SearchView>(`${project(code)}/search`, { q }), enabled: q.length > 0 });
  const recent = readRecent(code);
  const hits = found.data?.hits ?? [];
  const kinds = ["ALL", ...new Set(hits.map((h) => h.kind))];
  const shown = kind === "ALL" ? hits : hits.filter((h) => h.kind === kind);
  const pageRows = shown.slice((page - 1) * size, page * size);
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Search" subtitle="Press / or Ctrl+K on any page" />
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
          <div role="group" aria-label="Result kinds" className="flex flex-wrap gap-1 border-b border-border px-3 py-1.5">
            {kinds.map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={kind === k}
                onClick={() => change({ kind: k === "ALL" ? null : k, page: null })}
                className={`cursor-pointer rounded-sm border px-2 py-0.5 text-xs ${kind === k ? "border-accent bg-accent/10 text-fg" : "border-border-strong text-muted hover:bg-surface-2"}`}
              >
                {k === "ALL" ? "All" : k.charAt(0) + k.slice(1).toLowerCase()} <span className="num">{k === "ALL" ? hits.length : hits.filter((h) => h.kind === k).length}</span>
              </button>
            ))}
          </div>
          <DataTable
            label="Search results"
            data={pageRows}
            empty={<EmptyState title="Nothing you can see matches.">Try part of a name or an exact run id or key. Tables require whole-project view.</EmptyState>}
            columns={[
              columns.accessor("kind", { header: "Kind", cell: (c) => c.getValue().toLowerCase() }),
              columns.accessor("label", {
                header: "Name",
                cell: (c) => {
                  const target = hitLink(code, c.row.original);
                  if (c.row.original.kind === "RUN" && c.row.original.run_id !== null) return <RunLabel id={c.row.original.run_id} label={c.row.original.run_label} to={target.to}><Highlight text={c.getValue()} words={q} /></RunLabel>;
                  return (
                    <Link className="font-medium text-accent hover:underline" to={target.to}>
                      <Highlight text={c.getValue()} words={q} />
                    </Link>
                  );
                },
              }),
              columns.accessor("pipeline_code", { header: "Pipeline", cell: (c) => c.getValue() ?? "" }),
              columns.accessor("detail", { header: "Detail", cell: (c) => <Highlight text={searchDetail(c.row.original)} words={q} /> }),
            ]}
          />
          <Pager page={page} size={size} total={shown.length} onPage={(p) => change({ page: p === 1 ? null : String(p) })} />
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
