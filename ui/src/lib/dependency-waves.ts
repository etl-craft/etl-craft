/** Waves from the longest path to each node, so a graph reads left to right (or top to bottom). */
export function dependencyWaves(nodes: string[], dependsOn: Record<string, [string, string][]>): string[][] {
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
