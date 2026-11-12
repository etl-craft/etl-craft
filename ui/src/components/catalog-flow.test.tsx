import { describe, it, expect, vi, afterEach } from "vitest";
import { dependencyStyle, dependencyBadge, dependencySentence, definitionLabel, runCondition, runsWhen } from "@/lib/catalog-flow";
import { cleanup, render, screen } from "@testing-library/react";
import { TaskMapping, mappingLine, columnPaths } from "@/components/task-mapping";
import type { CatalogTask, CatalogEdge, CatalogDoc } from "@/lib/catalog";

describe("definition dependencies", () => {
  it.each([ ["SUCCESS", undefined, ""], ["HAS_DATA", undefined, "has data"], ["FAILURE", "7 4", "on failure"], ["ALWAYS", "2 4", "always"] ])("uses a neutral pattern and badge for %s", (kind, pattern, badge) => {
    expect(dependencyStyle(kind!)).toEqual({ stroke: "var(--muted)", strokeDasharray: pattern });
    expect(dependencyBadge(kind!)).toBe(badge);
    expect(JSON.stringify(dependencyStyle(kind!))).not.toMatch(/--(?:bad|ok|warn|run|success|failure)/);
  });
  it("explains data and repair consumption in words", () => {
    expect(dependencySentence("Schedule: manual", "LOAD", "SUCCESS")).toContain("pipeline is admitted");
    expect(dependencySentence("EXTRACT", "LOAD", "HAS_DATA")).toBe("LOAD runs only if EXTRACT succeeded and wrote rows");
    expect(definitionLabel({kind:"task", source:"a",target:"b",dependency_type:"SUCCESS",consume_repairs:"N"})).toContain("no repairs");
  });
  it.each([["ALL", "all"], ["ANY", "any"], ["N", "2 of 3"]])("explains %s", (condition, badge) => {
    const task = { label:"P.LOAD", pipeline:"P", handler:"SQL", documentation:null, documentation_version:null, target:null, sources:[], script:null, lineage:{state:"derived",reason:null}, mapping:{steps:[],edges:[],source:null,write:{action:null,managed_columns:[],keys:{}}}, script_kind:null, active_flag:"Y", target_active_flag:"Y", secrets:[], downstream:[], rules:[], runs:[], code:"LOAD", run_condition:condition,run_condition_count:2,upstream:[["A","SUCCESS","Y"],["B","SUCCESS","Y"],["C","SUCCESS","Y"]], retries:3,retry_on:"TRANSIENT",timeout_seconds:1800 } as CatalogTask;
    expect(runCondition(task)).toBe(badge);
    expect(runsWhen(task)).toContain("retries 3 times");
    expect(runsWhen(task)).toContain("30 minutes");
    expect(runsWhen(task)).toContain(condition === "N" ? "any 2 of" : condition.toLowerCase());
  });
  it("highlights all contributors to a target and everything a source feeds", () => {
    const edges = [{target_column:"amount",source_object:"raw.orders",source_column:"price"},{target_column:"amount",source_object:"raw.orders",source_column:"quantity"},{target_column:"tax",source_object:"raw.orders",source_column:"price"}] as CatalogEdge[];
    expect([...columnPaths(edges,"target:mart.orders:amount","mart.orders")]).toEqual([0,1]);
    expect([...columnPaths(edges,"source:raw.orders:price","mart.orders")]).toEqual([0,2]);
  });
});


afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function taskForMapping(state: "derived" | "declared" | "unavailable", edges: CatalogEdge[] = []): CatalogTask {
  return { label: "P.load", pipeline:"P", code:"load",handler:"PYTHON",run_condition:null,run_condition_count:null,documentation:null,documentation_version:null,target:null,sources:[],script:null,lineage:{state,reason:state === "unavailable" ? "Python utility scripts run arbitrary code; lineage is not derived" : null},mapping:{steps:[],edges,source:null,write:{action:null,managed_columns:[],keys:{}}},script_kind:"UTILITY",active_flag:"Y",target_active_flag:"Y",retries:0,retry_on:"NONE",timeout_seconds:0,secrets:[],upstream:[],downstream:[],rules:[],runs:[] };
}
it("labels declared lines distinctly and keeps derived lines plain", () => {
  expect(mappingLine("declared")).toEqual({ label:"declared",style:{stroke:"var(--muted)",strokeDasharray:"5 4"}});
  expect(mappingLine("derived").label).toBeUndefined();
});
it("renders unavailable lineage as a neutral note, never an alert", () => {
  vi.stubGlobal("matchMedia", () => ({matches:true}));
  render(<TaskMapping doc={{tables:[],rules:[]} as unknown as CatalogDoc} task={taskForMapping("unavailable")} />);
  expect(screen.getByRole("note")).toHaveTextContent("arbitrary code");
  expect(screen.queryByRole("alert")).toBeNull();
});
it("uses the diagram edges in the accessible mapping table", () => {
  vi.stubGlobal("matchMedia", () => ({matches:true}));
  const edges: CatalogEdge[] = [{task:"P.load",target_object:"mart.orders",target_column:"total",source_object:"raw.orders",source_column:"amount",transformation:"amount * 2"}];
  render(<TaskMapping doc={{tables:[],rules:[]} as unknown as CatalogDoc} task={taskForMapping("derived",edges)} />);
  expect(screen.getByRole("table", {name:"Task mapping"})).toHaveTextContent("raw.orders.amount");
  expect(screen.getByRole("table", {name:"Task mapping"})).toHaveTextContent("amount * 2");
  expect(screen.getByRole("table", {name:"Task mapping"})).toHaveTextContent("total");
});

it("renders dependency icons, neutral badges and the no-repairs marker", async () => {
  const { DependencyBadge } = await import("@/components/run-graph");
  const {container,rerender} = render(<DependencyBadge edge={{dependency_type:"HAS_DATA",consume_repairs:"Y"}} />);
  expect(container.querySelector(".lucide-database")).not.toBeNull();
  expect(screen.getByText("has data")).toBeVisible();
  rerender(<DependencyBadge edge={{dependency_type:"FAILURE",consume_repairs:"N"}} />);
  expect(container.querySelector(".lucide-x")).not.toBeNull();
  expect(screen.getByText(/on failure.*no repairs/)).toBeVisible();
  expect(container.innerHTML).not.toMatch(/--(?:bad|ok|warn|run)/);
  rerender(<DependencyBadge edge={{dependency_type:"SUCCESS",consume_repairs:"Y"}} />);
  expect(container).toBeEmptyDOMElement();
});
it("explains mixed dependency kinds instead of saying every upstream succeeds", () => {
  const task = taskForMapping("derived");
  task.upstream = [["P.extract","FAILURE","Y"],["P.notify","ALWAYS","Y"],["P.stage","HAS_DATA","Y"]];
  expect(runsWhen(task)).toContain("P.extract fails");
  expect(runsWhen(task)).toContain("P.notify finishes, whatever its outcome");
  expect(runsWhen(task)).toContain("P.stage succeeds and writes rows");
});
it("distinguishes source and target selections when a task reads its own target", () => {
  const edges = [{target_column:"amount",source_object:"mart.orders",source_column:"price"},{target_column:"price",source_object:"mart.orders",source_column:"amount"}] as CatalogEdge[];
  expect([...columnPaths(edges,"target:mart.orders:amount","mart.orders")]).toEqual([0]);
  expect([...columnPaths(edges,"source:mart.orders:amount","mart.orders")]).toEqual([1]);
});
