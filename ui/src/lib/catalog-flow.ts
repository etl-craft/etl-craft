import { describeCron } from "@/lib/format";
import type { CatalogTask, DefinitionEdge } from "@/lib/catalog";

export function runCondition(task: CatalogTask): string {
  return task.run_condition === "N" ? `${task.run_condition_count} of ${task.upstream.length}` : task.run_condition === "ANY" ? "Any" : "All";
}
export function runsWhen(task: CatalogTask): string {
  const names = task.upstream.map(([name]) => name).join(", ");
  const condition = task.run_condition === "N" ? `any ${task.run_condition_count} of` : task.run_condition === "ANY" ? "any of" : "all of";
  const clauses = task.upstream.map(([name,kind]) => kind === "FAILURE" ? `${name} fails` : kind === "ALWAYS" ? `${name} finishes, whatever its outcome` : kind === "HAS_DATA" ? `${name} succeeds and writes rows` : `${name} succeeds`);
  const when = !names ? "its pipeline is admitted" : task.upstream.every(([,kind]) => kind === "SUCCESS") ? `${condition} ${names} succeed` : `${condition} these conditions hold: ${clauses.join("; ")}`;
  const retry = task.retry_on === "NONE" ? "automatic retries are disabled" : `retries ${task.retries ?? "the configured number of"} times on ${(task.retry_on ?? "the configured policy").toLowerCase().replaceAll("_", " ")} errors`;
  const timeout = task.timeout_seconds ? `times out after ${task.timeout_seconds / 60} minutes` : "has no time limit";
  return `${task.code} runs when ${when}, ${retry}, ${timeout}.`;
}

export function dependencyStyle(kind: string): { stroke: string; strokeDasharray?: string } {
  return { stroke: "var(--muted)", strokeDasharray: kind === "FAILURE" ? "7 4" : kind === "ALWAYS" ? "2 4" : undefined };
}
export function dependencyBadge(kind: string): string {
  return kind === "HAS_DATA" ? "Has data" : kind === "FAILURE" ? "On failure" : kind === "ALWAYS" ? "Always" : "";
}
export function definitionLabel(edge: DefinitionEdge): string { return [dependencyBadge(edge.dependency_type), edge.consume_repairs === "N" ? "No repairs" : ""].filter(Boolean).join(" · "); }
export function dependencySentence(source: string, target: string, kind: string): string {
  if (source.startsWith("Schedule: ")) return `${target} becomes ready after its pipeline is admitted by the schedule or an explicit request`;
  return `${target} runs ${kind === "ALWAYS" ? `after ${source} finishes, whatever its outcome` : kind === "FAILURE" ? `only if ${source} failed` : kind === "HAS_DATA" ? `only if ${source} succeeded and wrote rows` : `only if ${source} succeeded`}`;
}

export function flowGraph(doc: import("@/lib/catalog").CatalogDoc, pipeline: import("@/lib/catalog").CatalogPipeline, graph: import("@/lib/types").Graph) {
  const upstream = doc.definition_edges.filter(e => e.kind === "pipeline" && e.target === pipeline.code);
  const external = doc.definition_edges.filter(e => e.kind === "task" && e.target.startsWith(`${pipeline.code}.`) && !e.source.startsWith(`${pipeline.code}.`));
  const downstream = doc.definition_edges.filter(e => e.kind === "pipeline" && e.source === pipeline.code);
  const entry = `Schedule: ${pipeline.schedule ? describeCron(pipeline.schedule) ?? "Custom schedule" : "Manual"}${pipeline.triggers.map(t => ` · trigger ${t.task}`).join("")}${pipeline.paused ? " · paused" : ""}`;
  const depends = { ...graph.depends_on };
  const roots = graph.waves[0] ?? [];
  const before = [...new Set([entry, ...upstream.map(e => `Upstream: ${e.source} · gate ${doc.gate_wait_minutes} min`), ...external.map(e => `Task gate: ${e.source} · gate ${doc.gate_wait_minutes} min`)])];
  roots.forEach(root => { depends[root] = [[entry, "SUCCESS"], ...upstream.map(edge => [`Upstream: ${edge.source} · gate ${doc.gate_wait_minutes} min`, edge.dependency_type] as [string,string])]; });
  external.forEach(edge => { const target = edge.target.split(".").at(-1)!; depends[target] = [...(depends[target] ?? []), [`Task gate: ${edge.source} · gate ${doc.gate_wait_minutes} min`, edge.dependency_type]]; });
  const after = downstream.map(e => `Downstream: ${e.target}`);
  after.forEach((name,index) => { depends[name] = (graph.waves.at(-1) ?? []).map(task => [task, downstream[index]!.dependency_type]); });
  return { ...graph, depends_on: depends, waves: [before, ...graph.waves, after].filter(wave => wave.length) };
}


export function flowLocation(project: string, pipeline: string, node: string): { project: string; kind: "pipelines" | "tasks"; name: string } | null {
  if (node.startsWith("Schedule: ")) return null;
  if (/^(Upstream|Downstream|Task gate): /.test(node)) {
    const parts = node.split(": ")[1]!.split(" · ")[0]!.split(".");
    if (node.startsWith("Task gate: ")) parts.pop();
    return { project: parts.length > 1 ? parts[0]! : project, kind:"pipelines", name:parts.at(-1)! };
  }
  return {project,kind:"tasks",name:`${pipeline}.${node}`};
}
