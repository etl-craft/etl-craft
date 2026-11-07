import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { TableObject } from "@/components/catalog-pages";
import { CatalogTree } from "@/components/catalog-tree";
import { pipelineGraph, tableLineage, type CatalogDoc } from "@/lib/catalog";

const column = (name: string, over: object = {}) => ({ name, data_type: "bigint", comment: null, declared_type: null, warehouse_type: "bigint", declared_nullable: null, warehouse_nullable: "Y", declared: true, warehouse_present: true, engine_managed: false, ...over });
const task = (pipeline: string, code: string, over: object = {}) => ({ label: `${pipeline}.${code}`, pipeline, code, handler: "SQL", run_condition: null, documentation: `${code} does its work.`, documentation_version: 1, target: null, sources: [], script: null, lineage_error: null, upstream: [], downstream: [], rules: [], runs: [], ...over });
const table = (name: string, over: object = {}) => {
  const [schema, short] = name.split(".");
  return { name, database: "w", schema, table: short, external: false, label: name, declared_kind: null, warehouse_kind: "TABLE", in_warehouse: true, warehouse_checked: true, findings: [], writers: [], readers: [], rules: [], columns: [column("id")], ...over };
};
const doc = {
  schema: "etl-craft/catalog/1", generated_at: "2026-11-07T10:00:00+00:00", compared_at: null, project: "demo", environment: "TEST", database: null, warehouse: "trino", sql_dialect: null,
  pipelines: [{ code: "LOAD", name: "LOAD", description: "Loads orders.", schedule: null, auto_restart_condition: "SCHEDULE", refresh_type: "FULL", sla_in_hours: null, tags: [], paused: null, tasks: ["LOAD.a", "LOAD.b"], depends_on: [], depended_on_by: [], runs: [] }],
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
