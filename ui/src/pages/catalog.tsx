import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { Loading, Notice, PageHeader } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { failureText, unavailableAction, useActionAvailability, useProjectInfo } from "@/hooks";
import { ApiError, getJson, project } from "@/lib/api";
import { useCatalog } from "@/lib/catalog";
import { catalogPath, type CatalogKind } from "@/lib/routes";
import type { LineageReparse, Report } from "@/lib/types";
import { useDocumentTitle } from "@/title";
import { ArrowLeft, ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "@/components/dropdown";
import { useParams, useSearchParams } from "react-router-dom";
import { AppLink as Link } from "@/components/navigation";
import { CatalogHome, GapsObject, PipelineObject, TableObject, TablesList, TaskObject } from "@/components/catalog-pages";
import { CatalogTree } from "@/components/catalog-tree";
import { SplitPane } from "@/components/split-pane";

type Done = { message?: string };

const untraced = (r: LineageReparse) => r.lineages.filter((l) => l.error);

function describeReparse(r: LineageReparse): string {
  const bad = untraced(r).length;
  const traced = r.lineages.length - bad;
  return bad
    ? `Lineage re-parsed with errors: ${traced} of ${r.lineages.length} task(s) traced; ${bad} could not be traced (listed on this page). Rebuild the catalog to show it.`
    : `Lineage re-parsed: ${traced} task(s) traced. Rebuild the catalog to show it in the pages below.`;
}

/** A re-parse's outcome stays on the page: a task whose SQL cannot be traced is named with its reason. */
function LineageResult({ result }: { result: LineageReparse }) {
  const bad = untraced(result);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Lineage re-parse</CardTitle>
        <span className="text-xs text-muted">
          {result.lineages.length - bad.length} of {result.lineages.length} task(s) traced
        </span>
      </CardHeader>
      {bad.length ? (
        <ul className="m-0 grid list-none gap-2 p-4 text-[13px]" aria-label="Tasks that could not be traced">
          {bad.map((l) => (
            <li key={l.task} className="break-words">
              <span className="font-mono font-medium">{l.task}</span>: <span className="text-bad">{l.error}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 p-4 text-muted">Every task was traced. Rebuild the catalog to show the new lineage in the pages below.</p>
      )}
    </Card>
  );
}

const KINDS: CatalogKind[] = ["pipelines", "tasks", "tables", "gaps"];

export function Catalog() {
  const { project: code = "", "*": rest = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const capabilities = useActionAvailability(code);
  const rebuildReason = unavailableAction(capabilities, "/docs");
  const lineageReason = unavailableAction(capabilities, "/lineage/re-parse");
  const versionsReason = unavailableAction(capabilities, "/docs/versions");
  const info = useProjectInfo(code);
  const [reparsed, setReparsed] = React.useState<LineageReparse | null>(null);
  const [chosen, setChosen] = React.useState<string | null>(null);
  // The built catalog is the last build; a missing build is shown in place of the explorer, with Rebuild still reachable.
  const built = useCatalog(code);
  const validate = useMutation({ mutationFn: () => getJson<Report>(`${project(code)}/validation`) });
  const report = validate.data;
  const missing = built.error instanceof ApiError ? built.error.message : built.error ? (built.error as Error).message : null;
  const [first = "", ...others] = rest.split("/").filter(Boolean);
  const kind = (KINDS as string[]).includes(first) ? (first as CatalogKind) : undefined;
  const name = others.join("/") || undefined;
  useDocumentTitle(kind === "gaps" ? "Catalog gaps" : name ? `${name} · Catalog` : "Catalog", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const [collapsed,setCollapsed]=React.useState(()=>window.matchMedia("(max-width: 1023px)").matches);
  const sidebar=React.useId();
  const tab = params.get("tab") ?? "overview";
  const onTab = (next: string) => {
    const copy = new URLSearchParams(params);
    if (next === "overview") copy.delete("tab");
    else copy.set("tab", next);
    setParams(copy, { replace: true });
  };
  const doc = built.data;
  const content = !doc ? null : kind === "pipelines" && name ? (
    <PipelineObject code={code} doc={doc} name={name} tab={tab} onTab={onTab} />
  ) : kind === "tasks" && name ? (
    <TaskObject code={code} doc={doc} name={name} tab={tab} onTab={onTab} />
  ) : kind === "tables" && !name ? (
    <TablesList code={code} doc={doc} />
  ) : kind === "tables" && name ? (
    <TableObject key={name} code={code} doc={doc} name={name} tab={tab} onTab={onTab} />
  ) : kind === "gaps" ? (
    <GapsObject code={code} doc={doc} />

  ) : (
    <CatalogHome code={code} doc={doc} />
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <PageHeader
        compact
        title="Catalog"
        actions={
          // One primary action; the rest are in one menu, each with what it does.
          <div className="flex flex-wrap items-start gap-2" role="group" aria-label="Catalog actions">
            {doc ? <Button aria-controls={sidebar} aria-expanded={!collapsed} onClick={()=>setCollapsed(value=>!value)}>{collapsed?<PanelLeftOpen aria-hidden className="size-4"/>:<PanelLeftClose aria-hidden className="size-4"/>}{collapsed?"Expand catalog sidebar":"Collapse catalog sidebar"}</Button>:null}
            <ActionButton<Done> code={code} label="Rebuild catalog" unavailableReason={rebuildReason} title="Rebuild the catalog" effect="Generates the catalog again from the current metadata." endpoint="/docs" body={() => ({})} askReason={false} describe={(r) => r.message ?? "The catalog was rebuilt."} onDone={() => void built.refetch()} variant="primary" />
            <DropdownMenu>
              <DropdownTrigger asChild>
                <Button aria-label="More catalog actions">
                  More
                  <ChevronDown className="size-3.5" aria-hidden />
                </Button>
              </DropdownTrigger>
              <DropdownContent align="end" className="w-80">
                <DropdownItem unavailableReason={unavailableAction(capabilities, "/validation", "GET")} onSelect={() => validate.mutate()} disabled={validate.isPending} className="grid gap-0.5">
                  <span className="font-medium">Validate metadata</span>
                  <span className="text-xs text-muted">Checks every pipeline and task definition without running anything.</span>
                </DropdownItem>
                <DropdownItem aria-label="Re-parse lineage" unavailableReason={lineageReason} onSelect={() => setChosen("lineage")} className="grid gap-0.5">
                    <span className="font-medium">Re-parse lineage</span>
                    <span className="text-xs text-muted">Works every task's lineage out again; the pages show it after the next rebuild.</span>
                </DropdownItem>
                <DropdownItem aria-label="Record catalog versions" unavailableReason={versionsReason} onSelect={() => setChosen("versions")} className="grid gap-0.5">
                    <span className="font-medium">Record catalog versions</span>
                    <span className="text-xs text-muted">Records the current definitions as the published catalog versions.</span>
                </DropdownItem>
              </DropdownContent>
            </DropdownMenu>
            <ActionButton<LineageReparse>
              code={code}
              label="Re-parse lineage"
              title="Re-parse lineage"
              effect="Works every task's lineage out again instead of reusing what was stored, then traces it. The catalog pages show the result after the next rebuild."
              endpoint="/lineage/re-parse" unavailableReason={lineageReason}
              body={() => ({})}
              askReason={false}
              describe={describeReparse}
              onDone={setReparsed}
              menu={{ open: chosen === "lineage", setOpen: (on) => setChosen(on ? "lineage" : null) }}
            />
            <ActionButton<Done> code={code} label="Record catalog versions" title="Record catalog versions" effect="Records the current definitions as the published catalog versions." endpoint="/docs/versions" unavailableReason={versionsReason} body={() => ({})} askReason={false} describe={() => "The catalog versions were recorded."} menu={{ open: chosen === "versions", setOpen: (on) => setChosen(on ? "versions" : null) }} />
          </div>
        }
      />
      {validate.isError ? <Notice>{failureText(validate.error)}</Notice> : null}
      {reparsed ? <LineageResult result={reparsed} /> : null}
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
          {missing.replace(/[.\s]+$/, "")}.{rebuildReason ? "" : " Use Rebuild catalog above."}
        </Notice>
      ) : null}
      {doc ? (
        <SplitPane
          id="catalog"
          collapsedLeft={collapsed}
          initial={0.26}
          className="lg:min-h-0 lg:flex-1"
          left={
            <Card id={sidebar} role="region" aria-label="Catalog sidebar" className="flex min-h-0 flex-1 flex-col overflow-hidden max-lg:max-h-80">
              <CatalogTree code={code} doc={doc} selected={{ kind, name }} />
            </Card>
          }
          right={
            <Card className="@container flex min-h-0 flex-1 flex-col overflow-hidden">
              {kind ? (
                <Link to={catalogPath(code)} className="m-4 mb-0 inline-flex w-fit items-center gap-1 text-sm text-accent hover:underline lg:hidden">
                  <ArrowLeft className="size-4" aria-hidden /> All catalog objects
                </Link>
              ) : null}
              {kind ? content : <div data-scroll-area className="min-h-0 flex-1 overflow-auto">{content}</div>}
            </Card>
          }
        />
      ) : null}
    </div>
  );
}
