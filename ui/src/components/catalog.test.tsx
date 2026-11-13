import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { GapsObject, PipelineObject, TableObject } from "@/components/catalog-pages";
import { CatalogInsights } from "@/components/catalog-insights";
import { CatalogTree } from "@/components/catalog-tree";
import { pipelineGraph, tableLineage, type CatalogDoc } from "@/lib/catalog";

const column = (name: string, over: object = {}) => ({ name, data_type: "bigint", comment: null, declared_type: null, warehouse_type: "bigint", declared_nullable: null, warehouse_nullable: "Y", declared: true, warehouse_present: true, engine_managed: false, ...over });
const task = (pipeline: string, code: string, over: object = {}) => ({ label: `${pipeline}.${code}`, pipeline, code, handler: "SQL", run_condition: null, documentation: `${code} does its work.`, documentation_version: 1, target: null, sources: [], script: null, lineage: { state: "derived", reason: null }, mapping: { steps: [], edges: [], source: null, write: { action: "CREATE_TABLE", managed_columns: [], keys: {} } }, script_kind: null, run_condition_count: null, active_flag: "Y", target_active_flag: "Y", retries: 0, retry_on: "TRANSIENT", timeout_seconds: 0, secrets: [], upstream: [], downstream: [], rules: [], runs: [], ...over });
const table = (name: string, over: object = {}) => {
  const [schema, short] = name.split(".");
  return { name, database: "w", schema, table: short, external: false, label: name, declared_kind: null, warehouse_kind: "TABLE", in_warehouse: true, warehouse_checked: true, findings: [], writers: [], readers: [], rules: [], columns: [column("id")], ...over };
};
const doc = {
  schema: "etl-craft/catalog/2", gate_wait_minutes: 60, definition_edges: [{kind:"task",source:"LOAD.a",target:"LOAD.b",dependency_type:"SUCCESS",consume_repairs:"Y"}], generated_at: "2026-11-07T10:00:00+00:00", compared_at: null, project: "demo", environment: "TEST", database: null, warehouse: "trino", sql_dialect: null,
  pipelines: [{ code: "LOAD", name: "LOAD", description: "Loads orders.", schedule: null, triggers: [], auto_restart_condition: "SCHEDULE", refresh_type: "FULL", sla_in_hours: null, tags: [], paused: null, tasks: ["LOAD.a", "LOAD.b"], depends_on: [], depended_on_by: [], runs: [] }],
  tasks: [task("LOAD", "a", { target: "stg.orders" }), task("LOAD", "b", { target: "ods.orders", sources: ["stg.orders"], upstream: [["LOAD.a", "SUCCESS"]] })],
  tables: [table("stg.orders", { writers: ["LOAD.a"], readers: ["LOAD.b"], columns: [column("id"), column("amount", { comment: "In cents" })] }), table("ods.orders", { writers: ["LOAD.b"] })],
  rules: [], scripts: [], table_edges: [{ source: "stg.orders", target: "ods.orders", task: "LOAD.b" }], column_edges: [], triggers: [], gaps: [],
} as unknown as CatalogDoc;

const wrap = (node: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);

describe("the catalog tree", () => {
  it("lists pipelines and warehouse schemas, and narrows to what the search finds, columns included", () => {
    wrap(<CatalogTree code="demo" doc={doc} selected={{}} />);
    expect(screen.getByRole("treeitem", { name: "LOAD" })).toBeTruthy();
    expect(screen.getByRole("treeitem", { name: /^stg \(1\)/ })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search the catalog"), { target: { value: "amount" } });
    const tree = screen.getByRole("tree", { name: "Catalog objects" });
    expect(within(tree).getByRole("treeitem", { name: "orders" })).toBeTruthy(); // stg.orders, by its column
    expect(within(tree).queryByRole("treeitem", { name: /^ods/ })).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("1 object match");
  });

  it("moves between items with the arrow keys and opens and closes groups with left and right", () => {
    wrap(<CatalogTree code="demo" doc={doc} selected={{}} />);
    const items = () => screen.getAllByRole("treeitem");
    items()[0]!.focus();
    expect(items()[0]!.tabIndex).toBe(0);
    expect(items()[1]!.tabIndex).toBe(-1); // one stop for Tab; the arrows do the rest
    fireEvent.keyDown(items()[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items()[1]);
    fireEvent.keyDown(items()[1]!, { key: "End" });
    expect(document.activeElement).toBe(items()[items().length - 1]);
    const pipelines = screen.getByRole("treeitem", { name: /^Pipelines/ });
    pipelines.focus();
    fireEvent.keyDown(pipelines, { key: "ArrowLeft" });
    expect(pipelines.getAttribute("aria-expanded")).toBe("false");
    fireEvent.keyDown(pipelines, { key: "ArrowRight" });
    expect(pipelines.getAttribute("aria-expanded")).toBe("true");
  });

  it("opens what the page shows and closes a group on a click", () => {
    wrap(<CatalogTree code="demo" doc={doc} selected={{ kind: "tasks", name: "LOAD.a" }} />);
    expect(screen.getByRole("treeitem", { name: "a" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("treeitem", { name: /^Pipelines/ }));
    expect(screen.queryByRole("treeitem", { name: "a" })).toBeNull();
  });
});

describe("a table's page", () => {
  it("shows its description from the writing task, its columns with a filter, and who writes and reads it", () => {
    wrap(<TableObject code="demo" doc={doc} name="stg.orders" tab="overview" onTab={() => undefined} />);
    expect(screen.getByText("a does its work.")).toBeTruthy();
    const columns = screen.getByRole("table", { name: "Columns" });
    expect(within(columns).getByText("amount")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Filter columns"), { target: { value: "cents" } });
    expect(within(screen.getByRole("table", { name: "Columns" })).queryByText("id")).toBeNull();
    const about = screen.getByLabelText("About this table");
    expect(within(about).getByRole("link", { name: "LOAD.a" })).toBeTruthy();
    expect(within(about).getByRole("link", { name: "LOAD.b" })).toBeTruthy();
  });

  it("says when a table is not in the build", () => {
    wrap(<TableObject code="demo" doc={doc} name="no.such" tab="overview" onTab={() => undefined} />);
    expect(screen.getByText(/No table no.such in this catalog build/)).toBeTruthy();
  });
});

describe("the catalog graphs", () => {
  it("draws a table's neighbours upstream and downstream", () => {
    const graph = tableLineage(doc, "stg.orders");
    expect(graph.waves).toEqual([["stg.orders"], ["ods.orders"]]);
    expect(graph.depends_on["ods.orders"]).toEqual([["stg.orders", "SUCCESS"]]);
  });

  it("draws a pipeline's tasks by code, in the order they wait", () => {
    const graph = pipelineGraph(doc, doc.pipelines[0]!);
    expect(graph.waves).toEqual([["a"], ["b"]]);
    expect(graph.depends_on.b).toEqual([["a", "SUCCESS"]]);
  });
});

describe("the catalog insights", () => {
  it("counts what is documented, written and read, and lists the tables no task writes", () => {
    wrap(<CatalogInsights code="demo" doc={doc} />);
    expect(screen.getByText("Tasks documented")).toBeTruthy();
    expect(screen.getByText("Tables written by a task")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Tables no task writes" })).toBeTruthy();
  });
});


describe("catalog gap remedies", () => {
  it("names the corrective step and hides unused comparison columns", () => {
    const gaps = [{ table: "stg.orders", column: null, attribute: "LINEAGE", state: "LINEAGE_ERROR", declared: null, deployed: null, reason: "SELECT could not be traced", tasks: ["LOAD.a"] }];
    wrap(<GapsObject code="demo" doc={{ ...doc, gaps }} />);
    const rows = screen.getByRole("table", { name: "Gaps" });
    expect(within(rows).getByRole("columnheader", { name: /^Next step\b/ })).toBeTruthy();
    expect(within(rows).getByText(/Correct the named task's SELECT/)).toBeTruthy();
    expect(within(rows).queryByRole("columnheader", { name: /^Declared\b/ })).toBeNull();
    expect(within(rows).queryByRole("columnheader", { name: /^Deployed\b/ })).toBeNull();
  });
});


it("shows sparse catalog run durations in the table and charts measured durations for larger series", () => {
  const run = { pipeline_run_id: 7, status: "SUCCESS", start: "2026-11-10T10:00:00Z", end: "2026-11-10T10:00:06Z" };
  const pipeline = { ...doc.pipelines[0]!, runs: [run] };
  wrap(<PipelineObject code="demo" doc={{ ...doc, pipelines: [pipeline] }} name="LOAD" tab="runs" onTab={() => undefined} />);
  expect(within(screen.getByRole("table", { name: "Recent runs" })).getByText("6s")).toBeTruthy();
  expect(screen.queryByRole("list", { name: "Run durations, newest on the right" })).toBeNull();
  cleanup();
  wrap(<PipelineObject code="demo" doc={{ ...doc, pipelines: [{ ...pipeline, runs: Array.from({ length: 5 }, (_, index) => ({ ...run, pipeline_run_id: index + 7 })) }] }} name="LOAD" tab="runs" onTab={() => undefined} />);
  expect(within(screen.getByRole("list", { name: "Run durations, newest on the right" })).getByRole("link", { name: "Run 7, Success, 6s" })).toBeTruthy();
});
