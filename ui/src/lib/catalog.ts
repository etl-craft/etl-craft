import { useQuery } from "@tanstack/react-query";
import { getText, project } from "@/lib/api";
import type { Graph } from "@/lib/types";

export interface CatalogRun {
  task_run_id?: number;
  task_run_label?: string;
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
  run_label?: string;
}
export interface CatalogPipeline {
  code: string;
  name: string;
  description: string | null;
  schedule: string | null;
  triggers: { task: string; pipeline: string; mode: string | null; timeout_minutes: string | null }[];
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
  lineage: { state: "derived" | "declared" | "unavailable"; reason: string | null };
  mapping: { steps: { kind: string; expression: string; name: string; logic?: {expression:string;columns:string[];label:string}[] }[]; edges: CatalogEdge[]; source: string | null; write: { action: string | null; managed_columns: string[]; keys: Record<string, string> } };
  script_kind: string | null;
  run_condition_count: number | null;
  active_flag: string;
  target_active_flag: string;
  retries: number | null;
  timeout_seconds: number | null;
  retry_on: string | null;
  secrets: string[];
  upstream: [string, string, string][];
  downstream: [string, string, string][];
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
  logic?:{expression:string;columns:string[];label:string}[];
  sql: string;
  id: number;
  name: string;
  type: string;
  level: string;
  table: string;
  task: string;
  key_column: string | null;
  observations: { status: string; passed: string | null; observed: string | null; detail: string | null; run_label?: string; pipeline_run_id: number }[];
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
  definition_edges: DefinitionEdge[];
  gate_wait_minutes: number;
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
    queryFn: async () => {
      const doc = JSON.parse(await getText(`${project(code)}/catalog/page`, { path: "catalog.json" })) as CatalogDoc;
      if (doc.schema !== "etl-craft/catalog/2") throw new Error(`Catalog schema ${doc.schema}: expected etl-craft/catalog/2; rebuild the catalog after upgrading.`);
      return doc;
    },
    retry: false,
    staleTime: 60_000,
  });
}

/** The comparison outcomes that are not a problem: they match, were not checked, or are expected. */
const FINE = new Set(["Matched", "Unchecked", "Not declared", "Expected before first deployment"]);

/** Whether a gap is something to act on, as the build words its states. */
export const isOpenGap = (gap: CatalogGap): boolean => !FINE.has(gap.state);

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
export function tableLineage(doc: CatalogDoc, name: string, depth = 2, direction: "both" | "up" | "down" = "both"): Graph {
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
  if (direction !== "down") walk(name, into);
  if (direction !== "up") walk(name, out);
  const dependsOn: Record<string, [string, string][]> = {};
  for (const e of doc.table_edges) if (keep.has(e.source) && keep.has(e.target)) dependsOn[e.target] = [...(dependsOn[e.target] ?? []), [e.source, "SUCCESS"]];
  return { waves: waves([...keep], dependsOn), conditional: [], depends_on: dependsOn };
}

/** A pipeline's tasks and what they wait for, by task code. */
export function pipelineGraph(doc: CatalogDoc, pipeline: CatalogPipeline): Graph {
  const byLabel = new Map(doc.tasks.filter((t) => t.pipeline === pipeline.code).map((t) => [t.label, t]));
  const dependsOn: Record<string, [string, string][]> = {};
  for (const task of byLabel.values()) {
    const inside = doc.definition_edges.filter(e => e.kind === "task" && e.target === task.label && byLabel.has(e.source)).map(e => [byLabel.get(e.source)!.code, e.dependency_type] as [string, string]);
    if (inside.length) dependsOn[task.code] = inside;
  }
  return { waves: waves([...byLabel.values()].map((t) => t.code), dependsOn), conditional: [], depends_on: dependsOn };
}

export interface ImpactRow {
  table: string;
  direction: "Upstream" | "Downstream";
  steps: number;
  task: string;
}

/** Every table upstream and downstream of one, how many steps away, and the task that makes the nearest step. */
export function impact(doc: CatalogDoc, name: string, depth = 4, direction: "both" | "up" | "down" = "both"): ImpactRow[] {
  const rows: ImpactRow[] = [];
  const walk = (label: ImpactRow["direction"], next: (table: string) => { table: string; task: string }[]) => {
    const seen = new Set([name]);
    let frontier = [name];
    for (let steps = 1; steps <= depth; steps++) {
      const found: string[] = [];
      for (const from of frontier)
        for (const hop of next(from)) {
          if (seen.has(hop.table)) continue;
          seen.add(hop.table);
          found.push(hop.table);
          rows.push({ table: hop.table, direction: label, steps, task: hop.task });
        }
      frontier = found;
    }
  };
  if (direction !== "down") walk("Upstream", (t) => doc.table_edges.filter((e) => e.target === t).map((e) => ({ table: e.source, task: e.task })));
  if (direction !== "up") walk("Downstream", (t) => doc.table_edges.filter((e) => e.source === t).map((e) => ({ table: e.target, task: e.task })));
  return rows;
}

/** The corrective action follows the failed comparison; it never changes warehouse data here. */
export function gapRemedy(gap: CatalogGap): string {
  if (/lineage/i.test(gap.attribute + gap.state)) return "Correct the named task's SELECT, refresh lineage, then rebuild the catalog.";
  if (/documentation/i.test(gap.attribute)) return "Add DOCUMENTATION to the task parameters and rebuild the catalog.";
  if (/unchecked/i.test(gap.state)) return "Rebuild the catalog with the warehouse comparison enabled.";
  return "Align the declared metadata and warehouse schema using config files or project migrations, then rebuild the catalog.";
}

export interface DefinitionEdge { kind: "task" | "pipeline"; target: string; source: string; dependency_type: string; consume_repairs: string }
