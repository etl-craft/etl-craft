import {RunGraph} from "@/components/run-graph";
import { useState } from "react";
import { Database, Download, Code, History, GitMerge, Eye, Trash2, ListPlus, ListMinus, Plus, Replace, Table2, Terminal, Bell, Hourglass, Network, ShieldCheck, FileCheck2, Eraser } from "lucide-react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { dependencyStyle, dependencyBadge, dependencySentence, definitionLabel, runCondition, runsWhen } from "@/lib/catalog-flow";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { TaskMapping, mappingLine, columnPaths } from "@/components/task-mapping";
import type { CatalogTask, CatalogEdge, CatalogDoc } from "@/lib/catalog";
import { MarkerType } from "@xyflow/react";
import type { Edge, Node } from "@xyflow/react";
const captured = vi.hoisted(() => ({ edges: [] as Edge[], nodes: [] as Node[], fit: {} as {minZoom?:number} }));
vi.mock("@xyflow/react", async importOriginal => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return { ...actual, ReactFlow: ({ edges, nodes, fitViewOptions }: { edges: Edge[]; nodes: Node[]; fitViewOptions:{minZoom?:number} }) => {
    captured.edges = edges; captured.nodes = nodes; captured.fit=fitViewOptions; return null;
  } };
});

describe("definition dependencies", () => {
  it.each([ ["SUCCESS", undefined, ""], ["HAS_DATA", undefined, "Has data"], ["FAILURE", "7 4", "On failure"], ["ALWAYS", "2 4", "Always"] ])("uses a neutral pattern and badge for %s", (kind, pattern, badge) => {
    expect(dependencyStyle(kind!)).toEqual({ stroke: "var(--muted)", strokeDasharray: pattern });
    expect(dependencyBadge(kind!)).toBe(badge);
    expect(JSON.stringify(dependencyStyle(kind!))).not.toMatch(/--(?:bad|ok|warn|run|success|failure)/);
  });
  it("explains data and repair consumption in words", () => {
    expect(dependencySentence("Schedule: manual", "LOAD", "SUCCESS")).toContain("pipeline is admitted");
    expect(dependencySentence("EXTRACT", "LOAD", "HAS_DATA")).toBe("LOAD runs only if EXTRACT succeeded and wrote rows");
    expect(definitionLabel({kind:"task", source:"a",target:"b",dependency_type:"SUCCESS",consume_repairs:"N"})).toContain("No repairs");
  });
  it.each([["ALL", "All"], ["ANY", "Any"], ["N", "2 of 3"]])("explains %s", (condition, badge) => {
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


beforeEach(()=>{vi.stubGlobal("ResizeObserver",class {observe(){} disconnect(){}});});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function taskForMapping(state: "derived" | "declared" | "unavailable", edges: CatalogEdge[] = []): CatalogTask {
  return { label: "P.load", pipeline:"P", code:"load",handler:"PYTHON",run_condition:null,run_condition_count:null,documentation:null,documentation_version:null,target:null,sources:[],script:null,lineage:{state,reason:state === "unavailable" ? "Python utility scripts run arbitrary code; lineage is not derived" : null},mapping:{steps:[],edges,source:null,write:{action:null,managed_columns:[],keys:{}}},script_kind:"UTILITY",active_flag:"Y",target_active_flag:"Y",retries:0,retry_on:"NONE",timeout_seconds:0,secrets:[],upstream:[],downstream:[],rules:[],runs:[] };
}
it("labels declared lines distinctly and keeps derived lines plain", () => {
  expect(mappingLine("declared")).toEqual({ label:"Declared",style:{stroke:"var(--kind-mauve)",strokeDasharray:"5 4"}});
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
  const { DependencyBadge } = await import("@/components/dependency-mark");
  const {container,rerender} = render(<DependencyBadge edge={{dependency_type:"HAS_DATA",consume_repairs:"Y"}} />);
  expect(container.querySelector(".lucide-database")).not.toBeNull();
  expect(screen.getByText("Has data")).toBeVisible();
  rerender(<DependencyBadge edge={{dependency_type:"FAILURE",consume_repairs:"N"}} />);
  expect(container.querySelector(".lucide-x")).not.toBeNull();
  expect(screen.getByText(/On failure.*No repairs/)).toBeVisible();
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

it("keeps named column ports through joins, filters, expressions and the write", () => {
  vi.stubGlobal("matchMedia", () => ({ matches:false }));
  const task = taskForMapping("derived", [
    {task:"P.load",target_object:"mart.orders",target_column:"total",source_object:"raw.orders",source_column:"price",transformation:"price * quantity"},
    {task:"P.load",target_object:"mart.orders",target_column:"total",source_object:"raw.orders",source_column:"quantity",transformation:"price * quantity"},
    {task:"P.load",target_object:"mart.orders",target_column:"id",source_object:"raw.orders",source_column:"id",transformation:"copy"},
  ]);
  task.target = "mart.orders"; task.sources = ["raw.orders"];
  task.mapping.steps = [{kind:"join",expression:"JOIN rates ON orders.id = rates.id",name:""},{kind:"filter",expression:"WHERE price > 0",name:""}];
  task.handler = "SQL"; task.script_kind = null;
  task.mapping.write.action = "SCD1_MERGE";
  const column = (name:string) => ({name,declared_type:"BIGINT",declared_nullable:"N"});
  const doc = {tables:[{name:"raw.orders",columns:[column("id"),column("price"),column("quantity")]},{name:"mart.orders",columns:[column("id"),column("total")]}],rules:[]} as unknown as CatalogDoc;
  render(<TaskMapping doc={doc} task={task}/>);
  const stages=["step:0","step:1","expression","write","target:mart.orders"].map(id=>captured.nodes.find(node=>node.id===id)!);
  expect(stages.every(node=>node.position.y===0)).toBe(true);
  expect(stages.every((node,index)=>index===0||node.position.x>stages[index-1]!.position.x)).toBe(true);
  expect(captured.fit.minZoom).toBe(1);
  expect(screen.getByRole("button",{name:"Reset zoom"})).toBeTruthy();
  expect(captured.edges.every(edge => edge.type === "mapping")).toBe(true);
  expect(captured.edges.every(edge => typeof edge.markerEnd === "object" && edge.markerEnd?.type === MarkerType.ArrowClosed)).toBe(true);
  expect(captured.edges.every(edge => edge.sourceHandle !== "object" && edge.targetHandle !== "object")).toBe(true);
  expect(captured.edges).toEqual(expect.arrayContaining([
    expect.objectContaining({source:"source:raw.orders",sourceHandle:"price",target:"step:0",targetHandle:"raw.orders.price"}),
    expect.objectContaining({source:"step:0",sourceHandle:"raw.orders.price",target:"step:1",targetHandle:"raw.orders.price"}),
    expect.objectContaining({source:"step:1",sourceHandle:"raw.orders.price",target:"expression",targetHandle:"raw.orders.price"}),
    expect.objectContaining({source:"expression",sourceHandle:"total",target:"write",targetHandle:"total"}),
    expect.objectContaining({source:"write",sourceHandle:"total",target:"target:mart.orders",targetHandle:"total"}),
  ]));
  const join = captured.nodes.find(node => node.id === "step:0")!;
  expect(join.data.columns).toEqual(expect.arrayContaining([expect.objectContaining({name:"raw.orders.price"}),expect.objectContaining({name:"raw.orders.quantity"})]));
  const expression = captured.nodes.find(node => node.id === "expression")!;
  expect(expression.data.columns).toEqual(expect.arrayContaining([
    expect.objectContaining({name:"raw.orders.price",output:false}),
    expect.objectContaining({name:"raw.orders.quantity",output:false}),
    expect.objectContaining({name:"total",input:false}),
  ]));
  const routes = captured.edges.map(edge => [edge.source,edge.sourceHandle,edge.target,edge.targetHandle]);
  fireEvent.click(screen.getByRole("button",{name:"Collapse all"}));
  expect(captured.nodes.every(node => !node.data.expanded)).toBe(true);
  expect(captured.edges.map(edge => [edge.source,edge.sourceHandle,edge.target,edge.targetHandle])).toEqual(routes);
  fireEvent.click(screen.getByRole("button",{name:"Expand all"}));
  expect(captured.nodes.every(node => node.data.expanded)).toBe(true);
  fireEvent.click(screen.getByRole("button",{name:"Table view"}));
  expect(screen.getByRole("table",{name:"Task mapping"})).toHaveTextContent("price * quantity");
  expect(screen.getByRole("table",{name:"Task mapping"})).toHaveTextContent("Derived");
});

it.each([
  ["SQL","CREATE_TABLE",null,Table2,"Create table"], ["SQL","SETUP_TABLE",null,Plus,"Set up table"],
  ["SQL","OVERWRITE_TABLE",null,Replace,"Overwrite"], ["SQL","APPEND_TABLE",null,ListPlus,"Append"],
  ["SQL","SCD1_MERGE",null,GitMerge,"SCD1 merge"], ["SQL","SCD2_MERGE",null,History,"SCD2 merge"],
  ["SQL","DROP_TABLE",null,Trash2,"Drop table"], ["SQL","DELETE_ROWS",null,ListMinus,"Delete rows"],
  ["SQL","CREATE_VIEW",null,Eye,"Create view"], ["SQL",null,null,Database,"Managed SQL"],
  ["PYTHON",null,"INGESTION",Download,"Python ingestion"], ["PYTHON",null,"UTILITY",Code,"Python utility"],
  ["SQL_SCRIPT",null,null,Terminal,"SQL script"], ["EMAIL_ALERT",null,null,Bell,"Alert"],
  ["EVENT_WAIT",null,null,Hourglass,"Event wait"], ["RUN_PIPELINE",null,null,Network,"Run pipeline"],
  ["BUSINESS_RULES",null,null,ShieldCheck,"Business rules"], ["FILE_VALIDATION",null,null,FileCheck2,"File validation"],
  ["ERASURE",null,null,Eraser,"Erasure"],
])("gives %s %s %s its own persistent task symbol", async (handler,action,kind,icon,label) => {
  const modulePath = "@/components/task-symbol";
  const {taskSymbol} = await import(modulePath);
  const task = taskForMapping("derived"); task.handler = handler as string;
  task.script_kind = kind as string | null; task.mapping.write.action = action as string | null;
  expect(taskSymbol(task)).toEqual({icon,label});
});
it("shares expandable symbol nodes while keeping column routes when collapsed", async () => {
  const modulePath = "@/components/diagram-node";
  const {DiagramNode} = await import(modulePath);
  function Example() { const [expanded,setExpanded] = useState(false); return <DiagramNode title="Orders" icon={Database} expanded={expanded} onExpanded={() => setExpanded(!expanded)}><span>amount column port</span></DiagramNode>; }
  render(<Example/>);
  expect(screen.queryByText("amount column port")).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"Expand Orders"}));
  expect(screen.getByText("amount column port")).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"Collapse Orders"}));
  expect(screen.queryByText("amount column port")).toBeNull();
});

it.each(["straight","offset","bypass"])("routes %s column arrows orthogonally outside node bodies", async kind => {
  const modulePath = "@/lib/mapping-arrows";
  const {mappingRoute,roundedMappingPath} = await import(modulePath);
  const box = {x:340,y:0,width:256,height:216};
  const source = kind === "bypass" ? {x:256,y:144} : {x:0,y:20};
  const target = kind === "bypass" ? {x:680,y:144} : {x:200,y:kind === "offset" ? 100 : 20};
  const points:number[][] = mappingRoute({sourceX:source.x,sourceY:source.y,targetX:target.x,targetY:target.y,lane:0.5,obstacles:kind === "bypass" ? [box] : []});
  expect(points[0]).toEqual([source.x,source.y]); expect(points.at(-1)).toEqual([target.x,target.y]);
  points.slice(1).forEach((point,index) => {
    const previous = points[index]!;
    expect(point[0] === previous[0] || point[1] === previous[1]).toBe(true);
    if (kind === "bypass") {
      const throughX = Math.max(point[0]!,previous[0]!) > box.x && Math.min(point[0]!,previous[0]!) < box.x+box.width;
      const throughY = Math.max(point[1]!,previous[1]!) > box.y && Math.min(point[1]!,previous[1]!) < box.y+box.height;
      expect(throughX && throughY).toBe(false);
    }
  });
  expect(roundedMappingPath(points)).not.toMatch(/NaN|Infinity/);
  if (kind === "bypass") expect(roundedMappingPath(points)).toContain("Q");
});

it.each(["42","COUNT(*)"])("uses row-set context, not an invented column input, for %s", transformation => {
  vi.stubGlobal("matchMedia",() => ({matches:false}));
  const task = taskForMapping("derived",[{task:"P.load",target_object:"mart.orders",target_column:"total",source_object:null,source_column:null,transformation}]);
  task.handler = "SQL"; task.target = "mart.orders"; task.sources = ["raw.orders"];
  task.mapping.steps = [{kind:"filter",expression:"WHERE id > 0",name:""}];
  if(transformation==="COUNT(*)")task.mapping.steps.push({kind:"aggregate",expression:"",name:"",logic:[{expression:"COUNT(*) AS total",columns:["total"],label:"Output"}]});
  task.mapping.write.action = "CREATE_TABLE";
  const doc = {tables:[{name:"raw.orders",columns:[{name:"id"}]},{name:"mart.orders",columns:[{name:"total"}]}],rules:[]} as unknown as CatalogDoc;
  render(<TaskMapping doc={doc} task={task}/>);
  expect(captured.nodes.find(node => node.id === "step:0")!.data.columns).toEqual([]);
  if(transformation==="COUNT(*)")expect(captured.edges).toEqual(expect.arrayContaining([expect.objectContaining({source:"step:1",sourceHandle:"total",target:"write",targetHandle:"total"})]));
  captured.edges.forEach(edge => {
    for (const [id,handle,input] of [[edge.source,edge.sourceHandle,false],[edge.target,edge.targetHandle,true]] as const) {
      const node = captured.nodes.find(node => node.id === id)!;
      if (handle === "object") expect(node.data.tableLevel).toBe(true);
      else {
        const port = (node.data.columns as {name:string;input?:boolean;output?:boolean}[]).find(port => port.name === handle);
        expect(port).toBeDefined();
        expect(input ? port!.input : port!.output).not.toBe(false);
      }
    }
  });
});

it("renders no controls or target box for unavailable lineage",()=>{
 vi.stubGlobal("matchMedia",()=>({matches:false}));
 const task=taskForMapping("unavailable");
 render(<TaskMapping doc={{tables:[],rules:[]} as unknown as CatalogDoc} task={task}/>);
 expect(screen.getByRole("note")).toBeVisible();expect(screen.queryByRole("toolbar")).toBeNull();
 expect(screen.queryByLabelText("Task mapping diagram")).toBeNull();
});
it("puts every conjunct exactly once in the accessible table",()=>{
 vi.stubGlobal("matchMedia",()=>({matches:true}));
 const task=taskForMapping("derived");task.mapping.steps=[{kind:"filter",name:"",expression:"",logic:[
  {expression:"a > 0",columns:["a"],label:""},{expression:"b = 'x'",columns:["b"],label:""},
  {expression:"c > 1 OR d < 2",columns:[],label:""},{expression:"a < b",columns:[],label:""},
 ]}];
 render(<TaskMapping doc={{tables:[],rules:[]} as unknown as CatalogDoc} task={task}/>);
 ["a > 0","b = 'x'","c > 1 OR d < 2","a < b"].forEach(text=>expect(screen.getAllByText(text)).toHaveLength(1));
 expect(screen.queryByRole("button",{name:"Table view"})).toBeNull();
 expect(screen.getByRole("button",{name:"Diagram"})).toBeVisible();
});
it("clears column highlighting with Escape and focuses search with slash",async ()=>{
 vi.stubGlobal("matchMedia",()=>({matches:false}));
 const task=taskForMapping("derived",[{task:"P.load",target_object:"mart.orders",target_column:"amount",source_object:"raw.orders",source_column:"a",transformation:"copy"},{task:"P.load",target_object:"mart.orders",target_column:"id",source_object:"raw.orders",source_column:"id",transformation:"copy"}]);task.sources=["raw.orders"];task.target="mart.orders";
 render(<TaskMapping doc={{tables:[{name:"mart.orders",columns:[{name:"amount"},{name:"id"}]}],rules:[]} as unknown as CatalogDoc} task={task}/>);
 const target=captured.nodes.find(node=>node.id==="target:mart.orders")!;
 fireEvent.keyDown(document,{key:"/"});expect(screen.getByRole("textbox",{name:"Find a column"})).toHaveFocus();
 const {act}=await import("@testing-library/react");act(()=>{(target.data.onSelect as (name:string)=>void)("target:mart.orders:amount");});expect(captured.edges.some(edge=>edge.style?.opacity===0.3)).toBe(true);fireEvent.keyDown(document,{key:"Escape"});expect(captured.edges.every(edge=>edge.style?.opacity===1)).toBe(true);
});

it("uses sentence-case stage and dependency labels instead of raw enum values",async ()=>{
 vi.stubGlobal("matchMedia",()=>({matches:false}));
 const task=taskForMapping("derived");task.handler="SQL";task.mapping.write.action="SCD2_MERGE";
 const {RunGraph}=await import("@/components/run-graph");
 const {container}=render(<RunGraph graph={{waves:[["load"]],depends_on:{load:[]},conditional:[]}} statuses={{}} focused={null} onFocus={()=>undefined} onOpen={()=>undefined} definition={{tasks:[task],edges:[]}} plain/>);
 const enums=new Set(["SUCCESS","HAS_DATA","FAILURE","ALWAYS","SCD2_MERGE","ALL","ANY"]);
 [...container.querySelectorAll("span,button")].forEach(element=>expect(enums.has(element.textContent??"")).toBe(false));
 expect(screen.queryByText("Succeeded",{exact:true})).toBeNull();
 expect(screen.queryByText("Has data",{exact:true})).toBeNull();
 expect(screen.getByText("SCD2 merge",{exact:true})).toBeVisible();
});

it("leaves a wire gutter between declared source and target boxes",()=>{
 vi.stubGlobal("matchMedia",()=>({matches:false}));
 const task=taskForMapping("declared");task.target="mart.orders";task.sources=["salesforce.Account"];
 render(<TaskMapping doc={{tables:[],rules:[]} as unknown as CatalogDoc} task={task}/>);
 const source=captured.nodes.find(node=>node.id==="source:salesforce.Account")!;
 const target=captured.nodes.find(node=>node.id==="target:mart.orders")!;
 expect(target.position.y).toBe(source.position.y);
 expect(target.position.x-source.position.x).toBeGreaterThanOrEqual(256+48);
});

it("keeps join and filter predicates out of the Target column",()=>{
 vi.stubGlobal("matchMedia",()=>({matches:true}));
 const task=taskForMapping("derived");task.mapping.steps=[{kind:"join",name:"",expression:"",logic:[{expression:"o.id = r.id",columns:["o.id","r.id"],label:""}]},{kind:"filter",name:"",expression:"",logic:[{expression:"o.amount > 0",columns:["o.amount"],label:""}]}];
 render(<TaskMapping doc={{tables:[],rules:[]} as unknown as CatalogDoc} task={task}/>);
 for(const logic of ["o.id = r.id","o.amount > 0"]){const row=screen.getByText(logic).closest("tr")!;expect(row.querySelector("td")?.textContent).toBe("");}
});
it("sizes entry and exit boxes to their names, without the kind prefix, before truncating",()=>{
 vi.stubGlobal("ResizeObserver",class{observe(){}disconnect(){}});
 const task=taskForMapping("derived");
 render(<RunGraph graph={{waves:[["Schedule: Daily at 06:00","Upstream: EXTRACT"],["load"],["Downstream: REPORT"]],depends_on:{load:[["Upstream: EXTRACT","SUCCESS"]]},conditional:[]}} statuses={{}} focused={null} onFocus={()=>undefined} onOpen={()=>undefined} definition={{tasks:[task],edges:[],schedule:"0 6 * * *"}} plain/>);
 for(const node of captured.nodes.filter(node=>node.id!=="load")){
  const name=node.id.replace(/^(Schedule|Upstream|Downstream): /,"");
  expect(node.data.width).toBeGreaterThanOrEqual(176);
  expect(node.data.width).toBeLessThanOrEqual(232);
  expect(node.data.width).toBeGreaterThanOrEqual(Math.min(232,name.length*7+104));
}
});
