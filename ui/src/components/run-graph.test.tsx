import { describe, expect, it } from "vitest";
import { layout } from "@/components/run-graph";
import type { Graph } from "@/lib/types";

const chain: Graph = { waves: [["a"], ["b"], ["c"]], conditional: [], depends_on: { b: [["a", "SUCCESS"]], c: [["b", "SUCCESS"]] } };
const at = (nodes: ReturnType<typeof layout>["nodes"], id: string) => nodes.find((n) => n.id === id)!.position;

describe("the graph layout", () => {
  it("runs a chain left to right by default", () => {
    const { nodes } = layout(chain, {}, null);
    expect(at(nodes, "a").x).toBeLessThan(at(nodes, "b").x);
    expect(at(nodes, "b").x).toBeLessThan(at(nodes, "c").x);
    expect(at(nodes, "a").y).toBe(at(nodes, "c").y);
  });

  it("runs a chain top to bottom for a tall pane, with the connectors on top and bottom", () => {
    const { nodes } = layout(chain, {}, null, undefined, false, "TB");
    expect(at(nodes, "a").y).toBeLessThan(at(nodes, "b").y);
    expect(at(nodes, "b").y).toBeLessThan(at(nodes, "c").y);
    expect(at(nodes, "a").x).toBe(at(nodes, "c").x);
    expect(nodes.every((n) => n.data.vertical)).toBe(true);
  });

  it("wraps a wide wave into rows of three when vertical", () => {
    const wide: Graph = { waves: [["a", "b", "c", "d"]], conditional: [], depends_on: {} };
    const { nodes } = layout(wide, {}, null, undefined, false, "TB");
    expect(new Set(nodes.map((n) => n.position.y)).size).toBe(2);
  });
});

it.each([
 ["HAS_DATA","Has data",undefined],
 ["FAILURE","On failure","7 4"],
 ["ALWAYS","Always","2 4"],
])("keeps the %s runtime edge consistent with its legend",(condition,label,dash)=>{
 const graph:Graph={waves:[["a"],["b"]],conditional:[],depends_on:{b:[["a",condition!]]}};
 const edge=layout(graph,{},null).edges[0]!;
 expect(edge.label).toBe(label);
 expect(edge.style?.strokeDasharray).toBe(dash);
});
