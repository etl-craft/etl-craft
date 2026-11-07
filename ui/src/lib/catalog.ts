import { useQuery } from "@tanstack/react-query";
import { getText, project } from "@/lib/api";
import type { Graph } from "@/lib/types";

export interface CatalogRun {
  pipeline_run_id: number;
  status: string;
  start: string | null;
  end: string | null;
  run_date?: string | null;
  sla_status?: string | null;
  started_by?: string | null;
  attempts?: number;
  source_count?: number | null;
  target_count?: number | null;
  insert_count?: number | null;
  update_count?: number | null;
  delete_count?: number | null;
  reject_count?: number | null;
  error_message?: string | null;
}
export interface CatalogPipeline {
  code: string;
  name: string;
  description: string | null;
  schedule: string | null;
  auto_restart_condition: string;
  refresh_type: string;
  sla_in_hours: number | null;
  tags: string[];
  paused: { paused_by: string; reason: string } | null;
  tasks: string[];
  depends_on: [string, string][];
  depended_on_by: string[];
  runs: CatalogRun[];
}
export interface CatalogTask {
  label: string;
  pipeline: string;
  code: string;
  handler: string;
  run_condition: string | null;
  documentation: string | null;
  documentation_version: number | null;
  target: string | null;
  sources: string[];
  script: string | null;
  lineage_error: string | null;
  upstream: [string, string][];
  downstream: [string, string][];
  rules: number[];
  runs: CatalogRun[];
}
export interface CatalogColumn {
  name: string;
  data_type: string | null;
  comment: string | null;
  declared_type: string | null;
  warehouse_type: string | null;
  declared_nullable: string | null;
  warehouse_nullable: string | null;
  declared: boolean;
  warehouse_present: boolean;
  engine_managed: boolean;
}
export interface CatalogTable {
  name: string;
  database: string;
  schema: string;
  table: string;
  external: boolean;
  label: string;
  declared_kind: string | null;
  warehouse_kind: string | null;
  in_warehouse: boolean;
  warehouse_checked: boolean;
  findings: string[];
  writers: string[];
  readers: string[];
  rules: number[];
  columns: CatalogColumn[];
}
export interface CatalogRule {
  id: number;
  name: string;
  type: string;
  level: string;
  table: string;
  task: string;
  key_column: string | null;
  observations: { status: string; passed: string | null; observed: string | null; detail: string | null; pipeline_run_id: number }[];
}
export interface CatalogEdge {
  target_object: string;
  target_column: string;
  source_object: string | null;
  source_column: string | null;
  transformation: string;
  task: string;
}
export interface CatalogGap {
  table: string;
  column: string | null;
  attribute: string;
  state: string;
  declared: string | null;
  deployed: string | null;
  reason: string;
  tasks: string[];
}
export interface CatalogDoc {
  schema: string;
  generated_at: string;
  compared_at: string | null;
  project: string;
  environment: string;
  database: string | null;
  warehouse: string | null;
  pipelines: CatalogPipeline[];
  tasks: CatalogTask[];
  tables: CatalogTable[];
  rules: CatalogRule[];
  scripts: { name: string; tasks: string[]; exists: boolean }[];
  table_edges: { source: string; target: string; task: string }[];
  column_edges: CatalogEdge[];
  gaps: CatalogGap[];
}

/** The last built catalog, read from the file the build wrote beside the site. */
export function useCatalog(code: string) {
  return useQuery({
    queryKey: ["catalog-doc", code],
    queryFn: async () => JSON.parse(await getText(`${project(code)}/catalog/page`, { path: "catalog.json" })) as CatalogDoc,
    retry: false,
    staleTime: 60_000,
  });
}

/** The warehouse tables, grouped by schema, as the tree shows them. */
export function schemasOf(doc: CatalogDoc): { schema: string; tables: CatalogTable[] }[] {
  const groups = new Map<string, CatalogTable[]>();
  for (const table of doc.tables) if (!table.external) groups.set(table.schema, [...(groups.get(table.schema) ?? []), table]);
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([schema, tables]) => ({ schema, tables: tables.sort((a, b) => a.table.localeCompare(b.table)) }));
}

/** A table's own type, preferring what the warehouse reports. */
export const typeOf = (column: CatalogColumn): string => column.warehouse_type ?? column.declared_type ?? column.data_type ?? "—";

/** Waves from the longest path to each node, so a graph reads left to right (or top to bottom). */
function waves(nodes: string[], dependsOn: Record<string, [string, string][]>): string[][] {
  const depth = new Map<string, number>();
  const visit = (node: string, seen: Set<string>): number => {
    if (depth.has(node)) return depth.get(node)!;
    if (seen.has(node)) return 0;
    seen.add(node);
    const d = Math.max(-1, ...(dependsOn[node] ?? []).map(([up]) => visit(up, seen))) + 1;
    depth.set(node, d);
    return d;
  };
  for (const node of nodes) visit(node, new Set());
  const out: string[][] = [];
  for (const node of nodes) (out[depth.get(node) ?? 0] ??= []).push(node);
  return out.filter(Boolean).map((wave) => wave.sort());
}

/** The tables upstream and downstream of one, up to `depth` steps each way, as a graph the task graph component draws. */
export function tableLineage(doc: CatalogDoc, name: string, depth = 3): Graph {
  const into = new Map<string, string[]>();
  const out = new Map<string, string[]>();
  for (const e of doc.table_edges) {
    into.set(e.target, [...(into.get(e.target) ?? []), e.source]);
    out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
  }
  const keep = new Set([name]);
  const walk = (start: string, next: Map<string, string[]>) => {
    let frontier = [start];
    for (let i = 0; i < depth; i++) {
      frontier = frontier.flatMap((n) => next.get(n) ?? []).filter((n) => !keep.has(n));
      frontier.forEach((n) => keep.add(n));
    }
  };
  walk(name, into);
  walk(name, out);
  const dependsOn: Record<string, [string, string][]> = {};
  for (const e of doc.table_edges) if (keep.has(e.source) && keep.has(e.target)) dependsOn[e.target] = [...(dependsOn[e.target] ?? []), [e.source, "SUCCESS"]];
  return { waves: waves([...keep], dependsOn), conditional: [], depends_on: dependsOn };
}

/** A pipeline's tasks and what they wait for, by task code. */
export function pipelineGraph(doc: CatalogDoc, pipeline: CatalogPipeline): Graph {
  const byLabel = new Map(doc.tasks.filter((t) => t.pipeline === pipeline.code).map((t) => [t.label, t]));
  const dependsOn: Record<string, [string, string][]> = {};
  for (const task of byLabel.values()) {
    const inside = task.upstream.filter(([label]) => byLabel.has(label)).map(([label, type]) => [byLabel.get(label)!.code, type] as [string, string]);
    if (inside.length) dependsOn[task.code] = inside;
  }
  return { waves: waves([...byLabel.values()].map((t) => t.code), dependsOn), conditional: [], depends_on: dependsOn };
}
