import * as React from "react";
import { Background, Controls, Handle, Position, ReactFlow, type Node, type NodeProps, type Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Button } from "@/components/ui/button";
import { DataTable, columnsOf } from "@/components/data-table";
import type { CatalogDoc, CatalogTask, CatalogEdge, CatalogColumn } from "@/lib/catalog";
import { cn } from "@/lib/utils";

type BoxData = { selection: string; title: string; columns: { name: string; detail: string }[]; declared: boolean; selected: Set<string>; onSelect: (name: string) => void } & Record<string, unknown>;
function MappingBox({ data }: NodeProps<Node<BoxData>>) {
  return <div className={cn("w-64 rounded-sm border bg-surface p-2 text-xs", data.declared ? "border-dashed border-border-strong" : "border-border-strong")}>
    <strong title={data.title} className="line-clamp-2 break-all pb-2">{data.declared ? "declared · " : ""}{data.title}</strong>
    <Handle className="!bg-border-strong" type="target" position={Position.Left} id="object" />
    {data.columns.map(column => <div key={column.name} className="relative h-16">
      <Handle className="!bg-border-strong" type="target" position={Position.Left} id={column.name} />
      <Button size="sm" variant="ghost" className={cn("!h-auto min-h-8 w-full !whitespace-normal justify-start break-all text-left", data.selected.has(`${data.selection}:${column.name}`) && "ring-2 ring-accent")} onClick={() => data.onSelect(`${data.selection}:${column.name}`)}><span className="line-clamp-3 break-all" title={`${column.name} ${column.detail}`}>{column.name} {column.detail}</span></Button>
      <Handle className="!bg-border-strong" type="source" position={Position.Right} id={column.name} />
    </div>)}
    <Handle className="!bg-border-strong" type="source" position={Position.Right} id="object" />
  </div>;
}
const nodeTypes = { mapping: MappingBox };
const fitOptions = { padding: 0.08, minZoom: 0.7, maxZoom: 1 };

export function mappingLine(state: string) {
  return { label: state === "declared" ? "declared" : undefined, style: { stroke: "var(--muted)", strokeDasharray: state === "declared" ? "5 4" : undefined } };
}

export function columnPaths(edges: CatalogEdge[], selected: string | null, target: string | null): Set<number> {
  const found = new Set<number>();
  edges.forEach((edge, index) => {
    if (!selected || selected === `target:${target}:${edge.target_column}` || selected === `source:${edge.source_object}:${edge.source_column}`) found.add(index);
  });
  return found;
}

/** One edge list feeds both the accessible table and the interactive column mapping. */
export function TaskMapping({ doc, task }: { doc: CatalogDoc; task: CatalogTask }) {
  const [table, setTable] = React.useState(() => window.matchMedia("(max-width: 480px)").matches);
  const [all, setAll] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [selected, setSelected] = React.useState<string | null>(null);
  const edges = task.mapping.edges;
  const targetTable = doc.tables.find(table => table.name === task.target);
  const targetColumns = new Map(targetTable?.columns.map(column => [column.name,column]) ?? []);
  const declared = task.lineage.state === "declared";
  const unavailable = task.lineage.state === "unavailable";
  const paths = columnPaths(edges, selected, task.target);
  const tableRows = edges.length ? edges : declared && task.target && task.sources[0] ? [{ target_object: task.target, target_column: "(table)", source_object: task.sources[0], source_column: null, transformation: "declared", task: task.label }] : [];
  const query = search.toLowerCase();
  const matching = edges.filter(edge => `${edge.target_column} ${edge.source_column ?? ""}`.toLowerCase().includes(query));
  const visible = new Set(matching.flatMap(edge => [`target:${task.target}:${edge.target_column}`, `source:${edge.source_object}:${edge.source_column}`]));
  const highlights = new Set<string>();
  paths.forEach(index => { const edge = edges[index]!; highlights.add(`target:${task.target}:${edge.target_column}`); highlights.add(`source:${edge.source_object}:${edge.source_column}`); });
  const nodes: Node<BoxData>[] = [];
  const lines: Edge[] = [];
  const add = (id: string, title: string, x: number, y: number, columns: BoxData["columns"]) => nodes.push({ id, type: "mapping", position: { x, y }, data: { selection: id.startsWith("expression:") ? `target:${task.target}` : id, title, columns: columns.filter(c => !query || (!id.startsWith("source:") && !id.startsWith("target:") && !id.startsWith("expression:")) || c.name.toLowerCase().includes(query) || visible.has(`${id.startsWith("expression:") ? `target:${task.target}` : id}:${c.name}`)), declared, selected: selected ? highlights : new Set(), onSelect: setSelected } });
  const sources = unavailable ? [] : task.sources;
  let sourceY = 0;
  sources.forEach(source => {
    const columns = doc.tables.find(t => t.name === source)?.columns ?? [];
    const used = new Set(edges.filter(e => e.source_object === source).map(e => e.source_column));
    const names = new Set([...columns.filter(c => all || used.has(c.name)).map(c => c.name), ...used].filter((n): n is string => !!n));
    add(`source:${source}`, source.replace(/^external:/, ""), 0, sourceY, [...names].map(name => ({ name, detail: "" })));
    sourceY += Math.max(160, names.size * 64 + 64);
  });
  let x = sources.length ? 340 : 0;
  task.mapping.steps.filter(step => step.kind !== "source").forEach((step, index) => { add(`step:${index}`, step.kind, x, 0, [{ name: step.expression, detail: "" }]); x += 340; });
  const expressions = [...new Set(edges.filter(e => e.transformation !== "copy" && e.transformation !== "declared").map(e => e.target_column))];
  expressions.forEach((column, index) => add(`expression:${column}`, "Computed column", x, index * 180, [{ name: column, detail: edges.find(e => e.target_column === column)!.transformation }]));
  if (expressions.length) x += 340;
  const rules = unavailable ? [] : doc.rules.filter(rule => rule.table === task.target && rule.type === "REJECT");
  if (rules.length) { add("rules", "Reject rules", x, 0, rules.map(rule => ({ name: rule.name, detail: rule.sql }))); x += 340; }
  if (!unavailable && task.mapping.write.action) { add("write", task.mapping.write.action, x, 0, [...Object.entries(task.mapping.write.keys).map(([name, detail]) => ({ name, detail })), ...(task.mapping.write.managed_columns.length ? [{ name: "Engine columns", detail: task.mapping.write.managed_columns.join(", ") }] : [])]); x += 340; }
  if (task.target) {
    const columns = targetTable?.columns ?? [];
    add(`target:${task.target}`, task.target, x, 0, columns.filter(c => all || !edges.length || edges.some(e => e.target_column === c.name)).map(c => ({ name: c.name, detail: `declared: ${c.declared_type ?? "not declared"} · ${c.declared_nullable === "N" ? "NOT NULL" : c.declared_nullable === "Y" ? "NULL" : "nullability not declared"}` })));
  }
  if (declared && !edges.length && task.target) sources.forEach(source => lines.push({ id: `declared:${source}`, source: `source:${source}`, sourceHandle: "object", target: `target:${task.target}`, targetHandle: "object", ...mappingLine("declared") }));
  const relational = nodes.filter(node => node.id.startsWith("step:"));
  const ending = nodes.filter(node => node.id === "rules" || node.id === "write");
  if (!edges.some(edge => edge.source_object) && !declared && !unavailable) {
    const chain = [...relational, ...ending];
    sources.forEach(source => { if (chain[0]) lines.push({ id: `rows:${source}`, source: `source:${source}`, sourceHandle: "object", target: chain[0].id, targetHandle: "object", style: mappingLine("derived").style }); });
  }
  edges.forEach((edge, index) => {
    if (!task.target) return;
    const expression = expressions.includes(edge.target_column) ? `expression:${edge.target_column}` : null;
    const path: [string,string][] = edge.source_object && edge.source_column ? [[`source:${edge.source_object}`,edge.source_column]] : [];
    path.push(...relational.map(node => [node.id,"object"] as [string,string]));
    if (expression) path.push([expression,edge.target_column]);
    path.push(...ending.map(node => [node.id,"object"] as [string,string]), [`target:${task.target}`,edge.target_column]);
    const style = { ...mappingLine(task.lineage.state).style, stroke: selected && paths.has(index) ? "var(--accent)" : "var(--muted)", strokeWidth: selected && paths.has(index) ? 3 : 1, opacity: selected && !paths.has(index) ? 0.2 : 1 };
    path.slice(1).forEach(([target,targetHandle],part) => {
      const [source,sourceHandle] = path[part]!;
      lines.push({ id: `${index}:${part}`,source,sourceHandle,target,targetHandle, label: mappingLine(task.lineage.state).label,style,type:"straight" });
    });
  });
  return <div className="grid min-w-0 gap-3">
    {task.lineage.reason ? <p role="note" className="rounded-sm border border-border bg-surface-2 p-3 text-sm text-muted">ⓘ {task.lineage.reason}</p> : null}
    {task.mapping.steps.some(step => step.kind === "source") ? <p className="break-words text-xs text-muted">Sources: {task.mapping.steps.filter(step => step.kind === "source").map(step => step.expression).join(" · ")}</p> : null}
    <div className="flex flex-wrap gap-2"><Button onClick={() => setTable(!table)}>{table ? "Diagram" : "Table view"}</Button><Button onClick={() => setAll(!all)}>{all ? "Used columns" : "Show all columns"}</Button><label className="text-sm">Find column <input value={search} onChange={e => setSearch(e.target.value)} className="rounded-sm border border-border bg-surface p-1" /></label></div>
    {table && unavailable && task.target ? <div><p className="text-sm font-medium">{task.target}</p><DataTable label="Declared target columns" data={targetTable?.columns ?? []} nextStep="Declare the target's active columns in columns.csv and rebuild the catalog." columns={columnsOf<CatalogColumn>([
      {id:"name",header:"Column",value:column => column.name}, {id:"type",header:"Declared type",value:column => column.declared_type ?? "not declared"}, {id:"nullable",header:"Nullable",value:column => column.declared_nullable === "Y" ? "yes" : column.declared_nullable === "N" ? "no" : "not declared"},
    ])} /></div> : null}
    {table && !unavailable ? <DataTable label="Task mapping" data={tableRows.filter(e => `${e.target_column} ${e.source_column ?? ""}`.toLowerCase().includes(search.toLowerCase()))} nextStep={task.lineage.reason ?? "Select a target column in the diagram to follow its sources."} columns={columnsOf<CatalogEdge>([
      { id: "target", header: "Target column", value: e => e.target_column }, { id: "source", header: "Source", value: e => `${e.source_object?.replace(/^external:/, "") ?? "constant"}.${e.source_column ?? ""}` }, { id: "expression", header: "Transformation", value: e => e.transformation }, { id: "state", header: "Lineage", value: () => task.lineage.state }, { id:"type",header:"Declared type",value:edge => targetColumns.get(edge.target_column)?.declared_type ?? "not declared" }, { id:"nullable",header:"Nullable",value:edge => targetColumns.get(edge.target_column)?.declared_nullable === "Y" ? "yes" : targetColumns.get(edge.target_column)?.declared_nullable === "N" ? "no" : "not declared" },
    ])} /> : !table && nodes.length ? <div className="h-[36rem] min-w-0 overflow-hidden rounded-sm border border-border" aria-label="Task mapping diagram"><ReactFlow nodes={nodes} edges={lines} nodeTypes={nodeTypes} defaultViewport={{x:24,y:40,zoom:0.85}} fitViewOptions={fitOptions} minZoom={0.2} maxZoom={2} nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}><Background /><Controls showInteractive={false} fitViewOptions={fitOptions} /></ReactFlow></div> : null}
  </div>;
}
