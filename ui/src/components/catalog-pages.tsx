import { useQuery } from "@tanstack/react-query";
import { Copy, Table2, Workflow, ListChecks, TriangleAlert } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Fact, FactList, Loading, Notice, SelectField } from "@/components/common";
import { RunBars } from "@/components/pipeline-parts";
import { RunGraph } from "@/components/run-graph";
import { StatusBadge } from "@/components/status";
import { Tabs } from "@/components/tabs";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { columnsOf, DataTable } from "@/components/data-table";
import { useRoleAtLeast, useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { isOpenGap, pipelineGraph, tableLineage, typeOf, type CatalogColumn, type CatalogDoc, type CatalogEdge, type CatalogRun, type CatalogTable, type CatalogTask } from "@/lib/catalog";
import { describeCron, formatDuration, formatTime } from "@/lib/format";
import { catalogPath, pipelinePath, taskPath } from "@/lib/routes";
import type { RunView, TablePreview } from "@/lib/types";
import { cn } from "@/lib/utils";

const link = "text-accent hover:underline";

function Crumbs({ code, trail }: { code: string; trail: { label: string; to?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-[13px] text-muted">
      <Link className={link} to={catalogPath(code)}>
        Catalog
      </Link>
      {trail.map((t) => (
        <React.Fragment key={t.label}>
          <span aria-hidden>›</span>
          {t.to ? (
            <Link className={link} to={t.to}>
              {t.label}
            </Link>
          ) : (
            <span>{t.label}</span>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}

function Title({ icon: Icon, name, copy, children }: { icon: typeof Table2; name: string; copy?: string; children?: React.ReactNode }) {
  const toast = useToast();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="grid size-8 place-items-center rounded-md bg-surface-2 text-muted">
        <Icon aria-hidden className="size-4" />
      </span>
      <h1 className="m-0 text-xl font-semibold">{name}</h1>
      {copy ? (
        <Button size="icon" variant="ghost" className="size-7" aria-label={`Copy ${copy}`} onClick={() => void navigator.clipboard.writeText(copy).then(() => toast("Name copied."))}>
          <Copy className="size-3.5" aria-hidden />
        </Button>
      ) : null}
      {children}
    </div>
  );
}

function Section({ title, aside, fill, className, children }: { title: string; aside?: React.ReactNode; fill?: boolean; className?: string; children: React.ReactNode }) {
  return (
    <Card className={cn(fill && "flex min-h-0 flex-1 flex-col", className)}>
      <CardHeader className="shrink-0">
        <CardTitle>{title}</CardTitle>
        {aside}
      </CardHeader>
      <div data-scroll-area={fill ? "" : undefined} className={cn(fill ? "min-h-0 flex-1 overflow-auto" : "overflow-x-auto p-4")}>{children}</div>
    </Card>
  );
}

/** An object's page: its breadcrumb, title and tabs stay put, and its body scrolls under them (`fit`: the body arranges itself to the window instead). */
function ObjectPage({ header, fit, children }: { header: React.ReactNode; fit?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="grid shrink-0 gap-3 px-4 pt-4">{header}</div>
      <div data-scroll-area className={cn("min-h-0 min-w-0 flex-1 p-4", fit ? "flex flex-col overflow-auto @3xl:overflow-hidden" : "overflow-auto")}>{children}</div>
    </div>
  );
}

const Links = ({ code, labels, kind }: { code: string; labels: string[]; kind: "tasks" | "tables" }) =>
  labels.length ? (
    <span className="flex min-w-0 flex-wrap gap-x-3 gap-y-0.5 break-all">
      {labels.map((label) => (
        <Link key={label} className={link} to={catalogPath(code, kind, label)}>
          {label}
        </Link>
      ))}
    </span>
  ) : (
    <span className="text-muted">None</span>
  );

/** What a run row says: its state and when it ran. */
function RunsTable({ code, pipeline, runs, task }: { code: string; pipeline: string; runs: CatalogRun[]; task?: boolean }) {
  const tz = useTimezone();
  if (!runs.length) return <p className="m-0 text-muted">No runs recorded in the last build.</p>;
  return (
    <DataTable
      label="Recent runs"
      data={runs}
      initialSort={[{ id: "run", desc: true }]}
      columns={columnsOf<CatalogRun>([
        { id: "run", header: "Run", value: (r) => r.pipeline_run_id, size: 90, cell: (r) => <Link className={`num ${link}`} to={`${pipelinePath(code, pipeline)}?run=${r.pipeline_run_id}`}>#{r.pipeline_run_id}</Link> },
        { id: "status", header: "Status", value: (r) => r.status, size: 130, cell: (r) => <StatusBadge status={r.status} /> },
        { id: "started", header: "Started", value: (r) => r.start, size: 190, cell: (r) => formatTime(r.start, tz) },
        { id: "duration", header: "Duration", value: (r) => (r.start && r.end ? new Date(r.end).getTime() - new Date(r.start).getTime() : null), size: 110, cell: (r) => formatDuration(r.start, r.end) },
        ...(task ? [{ id: "written", header: "Written", value: (r: CatalogRun) => (r.insert_count ?? 0) + (r.update_count ?? 0) + (r.delete_count ?? 0), size: 120, cell: (r: CatalogRun) => [["+", r.insert_count], ["~", r.update_count], ["−", r.delete_count]].filter(([, n]) => n).map(([sign, n]) => `${sign}${n}`).join(" ") || "—" }] : []),
      ])}
    />
  );
}

/** The catalog's front page: what it holds and what needs attention. */
export function CatalogHome({ code, doc }: { code: string; doc: CatalogDoc }) {
  const tz = useTimezone();
  const tables = doc.tables.filter((t) => !t.external);
  const columns = tables.reduce((n, t) => n + t.columns.length, 0);
  const undocumented = doc.tasks.filter((t) => !t.documentation).length;
  const unwritten = tables.filter((t) => t.writers.length === 0);
  const open = doc.gaps.filter(isOpenGap);
  const tile = (label: string, value: number | string) => (
    <div className="grid gap-1 rounded-lg border border-border bg-surface p-3">
      <span className="text-xs text-muted">{label}</span>
      <span className="text-2xl font-semibold">{value}</span>
    </div>
  );
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 p-4">
      <Title icon={Table2} name={`${doc.project} catalog`} />
      <p className="m-0 text-[13px] text-muted">
        Built {formatTime(doc.generated_at, tz)}
        {doc.compared_at ? `; compared with the warehouse ${formatTime(doc.compared_at, tz)}` : "; the warehouse was not compared"}. Rebuild it after metadata changes.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tile("Pipelines", doc.pipelines.length)}
        {tile("Tasks", doc.tasks.length)}
        {tile("Tables", tables.length)}
        {tile("Columns", columns)}
        {tile("Rules", doc.rules.length)}
        <Link to={catalogPath(code, "gaps")} aria-label={`${open.length} open gaps`} className="rounded-lg hover:ring-2 hover:ring-accent">
          {tile("Open gaps", open.length)}
        </Link>
      </div>
      <Section title="Needs attention">
        <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
          <li>
            <Link className={link} to={catalogPath(code, "gaps")}>
              {open.length} schema or lineage gap{open.length === 1 ? "" : "s"}
            </Link>
          </li>
          <li>{undocumented} task{undocumented === 1 ? "" : "s"} without documentation</li>
          <li>{unwritten.length} table{unwritten.length === 1 ? "" : "s"} no task writes{unwritten.length ? `: ${unwritten.slice(0, 6).map((t) => t.name).join(", ")}${unwritten.length > 6 ? "…" : ""}` : ""}</li>
        </ul>
      </Section>
    </div>
  );
}

/** A pipeline: what it does, its tasks, how they connect, and its latest runs. */
export function PipelineObject({ code, doc, name, tab, onTab }: { code: string; doc: CatalogDoc; name: string; tab: string; onTab: (tab: string) => void }) {
  const tz = useTimezone();
  const navigate = useNavigate();
  const pipeline = doc.pipelines.find((p) => p.code === name);
  const [focused, setFocused] = React.useState<string | null>(null);
  if (!pipeline) return <Notice className="m-4">No pipeline {name} in this catalog build.</Notice>;
  const tasks = doc.tasks.filter((t) => t.pipeline === pipeline.code);
  const graph = pipelineGraph(doc, pipeline);
  const tabs = [{ id: "overview", label: "Overview" }, { id: "lineage", label: "Task graph" }, { id: "runs", label: "Runs" }];
  const on = tabs.some((t) => t.id === tab) ? tab : "overview";
  return (
    <ObjectPage header={
      <>
      <Crumbs code={code} trail={[{ label: "Pipelines" }, { label: pipeline.code }]} />
      <Title icon={Workflow} name={pipeline.code} copy={pipeline.code}>
        <Link className={`ml-auto text-sm ${link}`} to={pipelinePath(code, pipeline.code)}>
          Open in the pipeline workspace
        </Link>
      </Title>
      <Tabs tabs={tabs} value={on} onChange={onTab} />
      </>
    }>
      {on === "overview" ? (
        <div className="grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_15rem]">
          <div className="grid min-w-0 grid-cols-1 gap-4">
            <Section title="Description">
              <p className="m-0 whitespace-pre-wrap text-[13px]">{pipeline.description || <span className="text-muted">No description. Set DESCRIPTION on the pipeline.</span>}</p>
            </Section>
            <Section title={`Tasks (${tasks.length})`}>
              <DataTable
                label="Tasks"
                data={tasks}
                columns={columnsOf<CatalogTask>([
                  { id: "task", header: "Task", value: (t) => t.code, size: 240, cell: (t) => <Link className={`font-medium ${link}`} to={catalogPath(code, "tasks", t.label)}>{t.code}</Link> },
                  { id: "handler", header: "Handler", value: (t) => t.handler, size: 120 },
                  { id: "reads", header: "Reads", value: (t) => t.sources.join(" "), size: 260, cell: (t) => (t.sources.length ? <Links code={code} labels={t.sources} kind="tables" /> : <span className="text-muted">—</span>) },
                  { id: "writes", header: "Writes", value: (t) => t.target ?? "", size: 240, cell: (t) => (t.target ? <Links code={code} labels={[t.target]} kind="tables" /> : <span className="text-muted">—</span>) },
                ])}
              />
            </Section>
          </div>
          <aside aria-label="About this pipeline" className="grid min-w-0 content-start gap-3">
            <h2 className="m-0 text-sm font-semibold">About this pipeline</h2>
            <FactList className="grid-cols-1 sm:grid-cols-1 lg:grid-cols-1">
              {pipeline.runs[0] ? (
                <Fact label="Last run">
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={pipeline.runs[0].status} /> {formatTime(pipeline.runs[0].start, tz)}
                  </span>
                </Fact>
              ) : null}
              <Fact label="Schedule">{pipeline.schedule ? <span title={pipeline.schedule}>{describeCron(pipeline.schedule) ?? <code className="font-mono">{pipeline.schedule}</code>}</span> : "Not scheduled"}</Fact>
              <Fact label="Refresh">{pipeline.refresh_type.toLowerCase()}</Fact>
              {pipeline.sla_in_hours ? <Fact label="SLA">{pipeline.sla_in_hours} h</Fact> : null}
              {pipeline.tags.length ? (
                <Fact label="Tags">
                  <span className="flex flex-wrap gap-1">
                    {pipeline.tags.map((tag) => (
                      <span key={tag} className="rounded bg-idle-bg px-1.5 py-0.5 text-xs text-idle">
                        {tag}
                      </span>
                    ))}
                  </span>
                </Fact>
              ) : null}
              {pipeline.paused ? <Fact label="Paused">{`${pipeline.paused.paused_by}: ${pipeline.paused.reason}`}</Fact> : null}
              {pipeline.depends_on.length ? <Fact label="Waits for">{pipeline.depends_on.map(([p]) => p).join(", ")}</Fact> : null}
              {pipeline.depended_on_by.length ? <Fact label="Waited on by">{pipeline.depended_on_by.join(", ")}</Fact> : null}
            </FactList>
          </aside>
        </div>
      ) : on === "lineage" ? (
        <div className="h-[28rem] overflow-hidden rounded-lg border border-border">
          <RunGraph fill plain graph={graph} statuses={{}} focused={focused} onFocus={setFocused} onOpen={(task) => navigate(catalogPath(code, "tasks", `${pipeline.code}.${task}`))} />
        </div>
      ) : (
        <Section title="Recent runs" aside={<RunBars project={code} runs={pipeline.runs as unknown as RunView[]} />}>
          <RunsTable code={code} pipeline={pipeline.code} runs={pipeline.runs} />
        </Section>
      )}
    </ObjectPage>
  );
}

function ColumnLineage({ code, edges }: { code: string; edges: CatalogEdge[] }) {
  if (!edges.length) return <p className="m-0 text-muted">No column lineage was traced for this selection.</p>;
  return (
    <DataTable
      label="Column lineage"
      data={edges}
      columns={columnsOf<CatalogEdge>([
        { id: "column", header: "Column", value: (e) => `${e.target_object}.${e.target_column}`, size: 300, cell: (e) => <span className="font-mono text-xs">{e.target_object}.{e.target_column}</span> },
        { id: "from", header: "Made from", value: (e) => (e.source_object ? `${e.source_object}.${e.source_column}` : "a constant"), size: 300, cell: (e) => <span className="font-mono text-xs">{e.source_object ? `${e.source_object}.${e.source_column}` : "a constant"}</span> },
        { id: "how", header: "How", value: (e) => e.transformation, size: 140, cell: (e) => <span className="text-muted">{e.transformation.toLowerCase()}</span> },
        { id: "task", header: "Task", value: (e) => e.task, size: 260, cell: (e) => <Link className={link} to={catalogPath(code, "tasks", e.task)}>{e.task}</Link> },
      ])}
    />
  );
}

/** A task: what it does, what it reads and writes, how its columns are made, its rules and runs. */
export function TaskObject({ code, doc, name, tab, onTab }: { code: string; doc: CatalogDoc; name: string; tab: string; onTab: (tab: string) => void }) {
  const task = doc.tasks.find((t) => t.label === name);
  if (!task) return <Notice className="m-4">No task {name} in this catalog build.</Notice>;
  const rules = doc.rules.filter((r) => r.task === task.label);
  const edges = doc.column_edges.filter((e) => e.task === task.label);
  const tabs = [{ id: "overview", label: "Overview" }, { id: "lineage", label: "Column lineage" }, { id: "runs", label: "Runs" }];
  const on = tabs.some((t) => t.id === tab) ? tab : "overview";
  return (
    <ObjectPage header={
      <>
      <Crumbs code={code} trail={[{ label: task.pipeline, to: catalogPath(code, "pipelines", task.pipeline) }, { label: task.code }]} />
      <Title icon={ListChecks} name={task.code} copy={task.label}>
        <Link className={`ml-auto text-sm ${link}`} to={taskPath(code, task.pipeline, task.code)}>
          Open the task's history
        </Link>
      </Title>
      <Tabs tabs={tabs} value={on} onChange={onTab} />
      </>
    }>
      {on === "overview" ? (
        <div className="grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_15rem]">
          <div className="grid min-w-0 grid-cols-1 gap-4">
            <Section title="Description">
              <p className="m-0 whitespace-pre-wrap text-[13px]">{task.documentation || <span className="text-muted">No documentation. Set the task's DOCUMENTATION parameter.</span>}</p>
            </Section>
            <Section title="Reads and writes">
              <FactList className="sm:grid-cols-2 lg:grid-cols-2">
                <Fact label="Reads">
                  <Links code={code} labels={task.sources} kind="tables" />
                </Fact>
                <Fact label="Writes">
                  <Links code={code} labels={task.target ? [task.target] : []} kind="tables" />
                </Fact>
                <Fact label="Waits for">
                  <Links code={code} labels={task.upstream.map(([label]) => label)} kind="tasks" />
                </Fact>
                <Fact label="Waited on by">
                  <Links code={code} labels={task.downstream.map(([label]) => label)} kind="tasks" />
                </Fact>
              </FactList>
              {task.lineage_error ? <Notice className="mt-3">{task.lineage_error}</Notice> : null}
            </Section>
            {rules.length ? (
              <Section title="Rules">
                <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
                  {rules.map((r) => (
                    <li key={r.id}>
                      <span className="font-medium">{r.name}</span> <span className="text-muted">{r.type.toLowerCase()} on {r.table}</span>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}
          </div>
          <aside aria-label="About this task" className="grid min-w-0 content-start gap-3">
            <h2 className="m-0 text-sm font-semibold">About this task</h2>
            <FactList className="grid-cols-1 sm:grid-cols-1 lg:grid-cols-1">
              <Fact label="Pipeline">{task.pipeline}</Fact>
              <Fact label="Handler">{task.handler}</Fact>
              <Fact label="Runs when">{task.run_condition ? task.run_condition.toLowerCase() : "all upstream succeed"}</Fact>
              <Fact label="Script">{task.script ?? "None"}</Fact>
              <Fact label="Documentation">{task.documentation_version ? `version ${task.documentation_version}` : "Not versioned"}</Fact>
            </FactList>
          </aside>
        </div>
      ) : on === "lineage" ? (
        <Section title="Column lineage" aside={<span className="text-xs text-muted">{edges.length} traced</span>}>
          <ColumnLineage code={code} edges={edges} />
        </Section>
      ) : (
        <Section title="Recent runs">
          <RunsTable code={code} pipeline={task.pipeline} runs={task.runs} task />
        </Section>
      )}
    </ObjectPage>
  );
}

/** The description of a table: what the tasks that write it say they do. */
function describe(doc: CatalogDoc, table: CatalogTable): CatalogTask[] {
  return table.writers.map((label) => doc.tasks.find((t) => t.label === label)).filter((t): t is CatalogTask => Boolean(t));
}

/** The first rows of the table, read from the warehouse when the tab opens. */
function TableData({ code, table }: { code: string; table: string }) {
  const rows = useQuery({ queryKey: ["table-preview", code, table], queryFn: () => getJson<TablePreview>(`${project(code)}/table-preview`, { table, limit: 100 }), retry: false, staleTime: 30_000 });
  if (rows.isPending) return <Loading what="the rows" />;
  if (rows.isError) return <Notice>{(rows.error as Error).message}</Notice>;
  const { columns, rows: data, more, limit } = rows.data;
  return (
    <div className="grid min-w-0 gap-2">
      <p className="m-0 text-xs text-muted">
        {data.length ? `${more ? `The first ${limit} rows` : `${data.length} row${data.length === 1 ? "" : "s"}`}, read from the warehouse now. Long values are cut.` : "The table has no rows."}
      </p>
      {data.length ? (
        <div className="max-h-[calc(100dvh-22rem)] overflow-auto rounded-lg border border-border">
          <DataTable
            label="Rows"
            data={data}
            columns={columnsOf<(string | null)[]>(columns.map((name, index) => ({ id: `${index}:${name}`, header: name, value: (row) => row[index] ?? null, size: 170, cell: (row) => (row[index] === null ? <span className="text-muted">null</span> : <span className="font-mono text-xs">{row[index]}</span>) })))}
          />
        </div>
      ) : null}
    </div>
  );
}

/** A table, as a data explorer shows it: description, columns with their types, then lineage, history and quality. */
export function TableObject({ code, doc, name, tab, onTab }: { code: string; doc: CatalogDoc; name: string; tab: string; onTab: (tab: string) => void }) {
  const navigate = useNavigate();
  const tz = useTimezone();
  const [filter, setFilter] = React.useState("");
  const [column, setColumn] = React.useState("");
  const [focused, setFocused] = React.useState<string | null>(null);
  const [depth, setDepth] = React.useState("2");
  const [showAll, setShowAll] = React.useState(false);
  const [direction, setDirection] = React.useState<"both" | "up" | "down">("both");
  const developer = useRoleAtLeast("developer");
  const table = doc.tables.find((t) => t.name === name);
  if (!table) return <Notice className="m-4">No table {name} in this catalog build.</Notice>;
  const writers = describe(doc, table);
  const rules = doc.rules.filter((r) => table.rules.includes(r.id));
  const gaps = doc.gaps.filter((g) => g.table === table.name && (showAll || isOpenGap(g)));
  const tabs = [
    { id: "overview", label: "Overview" },
    ...(developer ? [{ id: "data", label: "Data" }] : []),
    { id: "lineage", label: "Lineage" },
    { id: "columns", label: "Column lineage" },
    { id: "history", label: "History" },
    { id: "quality", label: "Quality" },
  ];
  const on = tabs.some((t) => t.id === tab) ? tab : "overview";
  const shown = table.columns.filter((c) => !filter || `${c.name} ${c.comment ?? ""} ${typeOf(c)}`.toLowerCase().includes(filter.toLowerCase()));
  const edges = doc.column_edges.filter((e) => e.target_object === table.name && (!column || e.target_column === column));
  const lastWrite = writers.flatMap((w) => w.runs).filter((r) => r.end).sort((a, b) => (b.end ?? "").localeCompare(a.end ?? ""))[0];
  const history = writers.flatMap((w) => w.runs.map((r) => ({ ...r, task: w.label, pipeline: w.pipeline }))).sort((a, b) => (b.start ?? "").localeCompare(a.start ?? "")).slice(0, 30);
  return (
    <ObjectPage fit={on === "overview"} header={
      <>
      <Crumbs code={code} trail={[{ label: table.schema || "schema" }, { label: table.table }]} />
      <Title icon={Table2} name={table.table} copy={table.name} />
      <Tabs tabs={tabs} value={on} onChange={onTab} />
      </>
    }>
      {on === "overview" ? (
        <div className="grid min-h-0 gap-4 @3xl:flex-1 @3xl:grid-cols-[minmax(0,1fr)_15rem] @3xl:grid-rows-[minmax(0,1fr)]">
          <div className="flex min-h-0 min-w-0 flex-col gap-4">
            <Section title="Description" className="shrink-0">
              {writers.length ? (
                <div className="grid max-h-28 gap-2 overflow-auto text-[13px]">
                  <p className="m-0 whitespace-pre-wrap">{writers.find((w) => w.documentation)?.documentation || <span className="text-muted">{writers[0]!.label} has no documentation.</span>}</p>
                  {writers.length > 1 ? <p className="m-0 text-xs text-muted">Written by {writers.length} tasks; each is listed under About this table.</p> : null}
                </div>
              ) : (
                <p className="m-0 text-muted">No task writes this table, so nothing describes it.</p>
              )}
            </Section>
            <Section fill className="max-h-96 @3xl:max-h-none" title={`Columns (${table.columns.length})`} aside={<input type="search" aria-label="Filter columns" placeholder="Filter columns…" value={filter} onChange={(event) => setFilter(event.target.value)} className="h-8 w-48 rounded-md border border-border-strong bg-surface px-2 text-[13px]" />}>
              {shown.length ? (
                <DataTable
                  label="Columns"
                  data={shown}
                  columns={columnsOf<CatalogColumn>([
                    { id: "column", header: "Column", value: (c) => c.name, size: 260, cell: (c) => <span className="font-mono text-xs font-medium">{c.name}{c.engine_managed ? <span className="ml-1.5 rounded bg-idle-bg px-1 text-[10px] text-idle">engine</span> : null}</span> },
                    { id: "type", header: "Type", value: (c) => typeOf(c), size: 200, cell: (c) => <span className="font-mono text-xs">{typeOf(c)}</span> },
                    { id: "declared", header: "Declared", value: (c) => c.declared_type ?? "", size: 200, cell: (c) => <span className={c.declared_type && c.warehouse_type && c.declared_type.toLowerCase() !== c.warehouse_type.toLowerCase() ? "font-mono text-xs text-warn" : "font-mono text-xs text-muted"}>{c.declared_type ?? "—"}</span> },
                    { id: "nullable", header: "Nullable", value: (c) => c.warehouse_nullable ?? c.declared_nullable ?? "", size: 100, cell: (c) => <span className="text-muted">{c.warehouse_nullable ?? c.declared_nullable ?? "—"}</span> },
                    { id: "comment", header: "Comment", value: (c) => c.comment ?? "", size: 300, cell: (c) => <span className="text-muted">{c.comment ?? ""}</span> },
                  ])}
                />
              ) : (
                <p className="m-0 text-muted">{table.columns.length ? "No column matches." : "No columns are declared or reported for this table."}</p>
              )}
            </Section>
          </div>
          <aside aria-label="About this table" className="grid min-h-0 min-w-0 content-start gap-3 overflow-auto">
            <h2 className="m-0 text-sm font-semibold">About this table</h2>
            <FactList className="grid-cols-1 sm:grid-cols-1 lg:grid-cols-1">
              <Fact label="Schema">{table.schema || "—"}</Fact>
              <Fact label="Type">{(table.warehouse_kind ?? table.declared_kind ?? "table").toLowerCase()}</Fact>
              <Fact label="Data source">{doc.warehouse ?? "Not compared"}</Fact>
              <Fact label="In warehouse">{table.warehouse_checked ? (table.in_warehouse ? "Yes" : "Not found") : "Not checked"}</Fact>
              <Fact label="Last written">{lastWrite ? formatTime(lastWrite.end, tz) : "No run recorded"}</Fact>
              <Fact label="Written by">
                <Links code={code} labels={table.writers} kind="tasks" />
              </Fact>
              <Fact label="Read by">
                <Links code={code} labels={table.readers} kind="tasks" />
              </Fact>
            </FactList>
          </aside>
        </div>
      ) : on === "data" ? (
        <TableData code={code} table={table.name} />
      ) : on === "lineage" ? (
        <div className="grid min-w-0 gap-2">
          <div className="flex flex-wrap items-end gap-3">
            <SelectField compact label="Direction" value={direction} onChange={(v) => setDirection(v as typeof direction)}>
              <option value="both">Upstream and downstream</option>
              <option value="up">Upstream only</option>
              <option value="down">Downstream only</option>
            </SelectField>
            <SelectField compact label="Depth" value={depth} onChange={setDepth}>
              {["1", "2", "3", "4"].map((d) => (
                <option key={d} value={d}>
                  {d} step{d === "1" ? "" : "s"}
                </option>
              ))}
            </SelectField>
            <span className="pb-1 text-xs text-muted">Select a table to open it.</span>
          </div>
          <div className="h-[calc(100dvh-24rem)] min-h-72 overflow-hidden rounded-lg border border-border">
            <RunGraph fill plain graph={tableLineage(doc, table.name, Number(depth), direction)} statuses={{}} focused={focused ?? table.name} onFocus={setFocused} onOpen={(next) => navigate(catalogPath(code, "tables", next))} />
          </div>
        </div>
      ) : on === "columns" ? (
        <Section
          title="Column lineage"
          aside={
            <SelectField compact label="Column" value={column} onChange={setColumn}>
              <option value="">All columns</option>
              {table.columns.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </SelectField>
          }
        >
          <ColumnLineage code={code} edges={edges} />
        </Section>
      ) : on === "history" ? (
        <Section title="Recent writes">
          {writers.some((w) => w.runs.length === 0) ? <p className="mt-0 text-xs text-muted">No run is recorded for {writers.filter((w) => w.runs.length === 0).map((w) => w.label).join(", ")}.</p> : null}
          {history.length ? (
            <DataTable
              label="Recent writes"
              data={history}
              columns={columnsOf<(typeof history)[number]>([
                { id: "task", header: "Task", value: (r) => r.task, size: 280, cell: (r) => <Link className={link} to={catalogPath(code, "tasks", r.task)}>{r.task}</Link> },
                { id: "run", header: "Run", value: (r) => r.pipeline_run_id, size: 90, cell: (r) => <span className="num">#{r.pipeline_run_id}</span> },
                { id: "status", header: "Status", value: (r) => r.status, size: 130, cell: (r) => <StatusBadge status={r.status} /> },
                { id: "started", header: "Started", value: (r) => r.start, size: 190, cell: (r) => formatTime(r.start, tz) },
                { id: "duration", header: "Duration", value: (r) => (r.start && r.end ? new Date(r.end).getTime() - new Date(r.start).getTime() : null), size: 110, cell: (r) => formatDuration(r.start, r.end) },
                { id: "rows", header: "Rows", value: (r) => (r.insert_count ?? 0) + (r.update_count ?? 0) + (r.delete_count ?? 0), size: 120, cell: (r) => [["+", r.insert_count], ["~", r.update_count], ["−", r.delete_count]].filter(([, n]) => n).map(([sign, n]) => `${sign}${n}`).join(" ") || "—" },
              ])}
            />
          ) : (
            <p className="m-0 text-muted">No task that writes this table has a recorded run.</p>
          )}
        </Section>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-4">
          <Section title={`Rules (${rules.length})`}>
            {rules.length ? (
              <ul className="m-0 grid list-none gap-2 p-0 text-[13px]">
                {rules.map((r) => {
                  const last = r.observations[0];
                  return (
                    <li key={r.id} className="flex flex-wrap items-center gap-2">
                      {last ? <StatusBadge status={last.status} /> : <span className="text-muted">No result</span>}
                      <span className="font-medium">{r.name}</span>
                      <span className="text-muted">{r.type.toLowerCase()}, {r.level.toLowerCase()}{last?.observed ? `; observed ${last.observed}` : ""}</span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="m-0 text-muted">No business rule checks this table.</p>
            )}
          </Section>
          <Section
            title={`${showAll ? "Everything checked" : "Gaps"} (${gaps.length})`}
            aside={
              <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
                <input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />
                Show matched and undeclared too
              </label>
            }
          >
            {gaps.length ? <GapRows code={code} gaps={gaps} /> : <p className="m-0 text-muted">{table.warehouse_checked ? "No gaps: every checked attribute matches or is not declared." : "The warehouse was not compared in this build."}</p>}
          </Section>
        </div>
      )}
    </ObjectPage>
  );
}

function GapRows({ code, gaps }: { code: string; gaps: CatalogDoc["gaps"] }) {
  return (
    <DataTable
      label="Gaps"
      data={gaps}
      columns={columnsOf<CatalogDoc["gaps"][number]>([
        { id: "object", header: "Object", value: (g) => `${g.table}${g.column ? `.${g.column}` : ""}`, size: 300, cell: (g) => <span className="font-mono text-xs"><Link className={link} to={catalogPath(code, "tables", g.table)}>{g.table}</Link>{g.column ? `.${g.column}` : ""}</span> },
        { id: "attribute", header: "Attribute", value: (g) => g.attribute, size: 150, cell: (g) => g.attribute.toLowerCase().replace(/_/g, " ") },
        { id: "state", header: "State", value: (g) => g.state, size: 140, cell: (g) => g.state.toLowerCase().replace(/_/g, " ") },
        { id: "declared", header: "Declared", value: (g) => g.declared ?? "", size: 160, cell: (g) => <span className="font-mono text-xs">{g.declared ?? "—"}</span> },
        { id: "deployed", header: "Deployed", value: (g) => g.deployed ?? "", size: 160, cell: (g) => <span className="font-mono text-xs">{g.deployed ?? "—"}</span> },
        { id: "why", header: "Why", value: (g) => g.reason, size: 380, cell: (g) => <span className="text-muted">{g.reason}</span> },
      ])}
    />
  );
}

/** Every schema and lineage gap, with the state to filter by. */
export function GapsObject({ code, doc }: { code: string; doc: CatalogDoc }) {
  const [state, setState] = React.useState("OPEN");
  const states = [...new Set(doc.gaps.map((g) => g.state))].sort();
  const shown = doc.gaps.filter((g) => (state === "ALL" ? true : state === "OPEN" ? isOpenGap(g) : g.state === state));
  return (
    <ObjectPage header={
      <>
      <Crumbs code={code} trail={[{ label: "Gaps" }]} />
      <Title icon={TriangleAlert} name="Schema and lineage gaps" />
      <p className="m-0 text-[13px] text-muted">Where what the project declares, what the warehouse holds and what the SQL reads disagree. Unchecked comparisons are never counted as matched.</p>
      <SelectField compact label="Show" value={state} onChange={setState}>
        <option value="OPEN">Open gaps</option>
        <option value="ALL">Everything checked</option>
        {states.map((s) => (
          <option key={s} value={s}>
            {s.toLowerCase().replace(/_/g, " ")}
          </option>
        ))}
      </SelectField>
      </>
    }>
      <Card className="overflow-x-auto">{shown.length ? <GapRows code={code} gaps={shown.slice(0, 500)} /> : <p className="m-0 p-4 text-muted">Nothing to show for this selection.</p>}</Card>
      {shown.length > 500 ? <p className="m-0 text-xs text-muted">The first 500 of {shown.length} are shown; narrow it by state.</p> : null}
    </ObjectPage>
  );
}
