import {useLegend} from "@/components/legend";
import {mappingStageEntry,highlightedEntry,MappingLogicMark,mappingLogicEntry,MappingConditions} from "@/components/diagram-key";
import {CatalogWidthButton} from "@/components/catalog-width";
import {fitDiagram,readableFit} from "@/lib/diagram-viewport";
import * as React from "react";
import { Background, Handle, MarkerType, NodeResizer, useReactFlow, useUpdateNodeInternals, Position, ReactFlow, type Node, type NodeProps, type Edge, type EdgeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Database, GitMerge, Filter, Sigma, Layers, FunctionSquare, ShieldCheck, type LucideIcon } from "lucide-react";
import { catalogPath } from "@/lib/routes";
import { Link } from "react-router-dom";
import { DiagramToolbar, DiagramChip } from "@/components/diagram-toolbar";
import { mappingFields, stageRows, stageLabel, sourceAliases } from "@/lib/mapping-logic";
import { kindColor, kindLabels } from "@/components/task-symbol";
import { taskSymbol } from "@/components/task-symbol";
import { diagramKeys, DiagramNode, DiagramEdge, useDiagramExpansion } from "@/components/diagram-node";
import { Button } from "@/components/ui/button";
import { DataTable, columnsOf } from "@/components/data-table";
import type { CatalogDoc, CatalogTask, CatalogEdge } from "@/lib/catalog";
import { mappingRoute, roundedMappingPath } from "@/lib/mapping-arrows";
import { cn } from "@/lib/utils";

type Port = { name: string; detail: string; logic?:string; selection?: string; input?: boolean; output?: boolean };
type BoxData = { selection: string; title: string; description?: string; columns: Port[]; declared: boolean; selected: Set<string>; onSelect: (name: string) => void; expanded: boolean; onExpanded: () => void; tableLevel?: boolean; kind:string; conditions?:string[]; icon: LucideIcon; size?: NodeSize; onResize: (id: string, size: NodeSize) => void } & Record<string, unknown>;
type NodeSize = { width: number; height?: number };
/** A node lists this many column rows before its list scrolls; a resized node fills its height instead. */
const SHOWN_ROWS = 5;
const ROW_HEIGHT = 32;
const HEADER_HEIGHT = 44;
function MappingBox({ id, data }: NodeProps<Node<BoxData>>) {
  const expanded = data.expanded;
  const [engine,setEngine]=React.useState(false);
  const list = React.useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = React.useState({top: HEADER_HEIGHT, height: SHOWN_ROWS * ROW_HEIGHT + 8, scroll: 0});
  const updateNodeInternals = useUpdateNodeInternals();
  React.useLayoutEffect(() => {
    const element = list.current;
    if (!element) return;
    const measure = () => setViewport(previous => {
      const next = {top: element.offsetTop, height: element.clientHeight, scroll: element.scrollTop};
      return previous.top === next.top && previous.height === next.height && previous.scroll === next.scroll ? previous : next;
    });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [expanded, data.columns, data.size, engine]);
  React.useLayoutEffect(() => { updateNodeInternals(id); }, [id, expanded, data.columns, data.size, viewport, updateNodeInternals]);
  const objectPorts = data.tableLevel ? <>{!id.startsWith("source:") ? <Handle type="target" position={Position.Left} id="object" style={{top:expanded ? 48 : 64}}/> : null}{!id.startsWith("target:") && id!=="expression" ? <Handle type="source" position={Position.Right} id="object" style={{top:expanded ? 48 : 64}}/> : null}</> : null;
  const collapsedPorts = <>{data.columns.map(column => <React.Fragment key={column.name}>{column.input !== false ? <Handle type="target" position={Position.Left} id={column.name}/> : null}{column.output !== false ? <Handle type="source" position={Position.Right} id={column.name}/> : null}</React.Fragment>)}{objectPorts}</>;
  const size = data.size;
  const fixedHeight = size?.height;
  const logicLabel = kindLabels[data.kind] ?? "Logic";
  return <><NodeResizer minWidth={160} minHeight={HEADER_HEIGHT + ROW_HEIGHT * 2} onResize={(_, next) => data.onResize(id, { width: next.width, height: next.height })}/><DiagramNode title={data.title} width={size?.width ?? (data.declared?(id.startsWith("source:")?320:256):160)} height={fixedHeight} bodyClassName={fixedHeight!==undefined ? "flex min-h-0 flex-1 flex-col" : undefined} color={kindColor(data.kind)} chip={data.declared ? <DiagramChip>Declared</DiagramChip> : undefined} description={data.conditions?.length ? <MappingConditions conditions={data.conditions}/> : undefined} icon={data.icon} expanded={expanded} onExpanded={data.onExpanded} headingClassName="h-10" collapsedPorts={collapsedPorts} className={cn("mapping-node",data.declared && "border-dashed",data.selected.has(`${id}:object`) && "ring-2 ring-accent")}>
    {objectPorts}
    {data.columns.map((column, index) => {
      // Off-screen columns stay wired at the list boundary while their rows scroll.
      const top = viewport.top + Math.max(4, Math.min(viewport.height - 4, index * ROW_HEIGHT + ROW_HEIGHT / 2 - viewport.scroll));
      return <React.Fragment key={column.name}>
        {column.input !== false ? <Handle style={{top}} title={column.name} className="!bg-border-strong" type="target" position={Position.Left} id={column.name}/> : null}
        {column.output !== false ? <Handle style={{top}} title={column.name} className="!bg-border-strong" type="source" position={Position.Right} id={column.name}/> : null}
      </React.Fragment>;
    })}
    <div ref={list} onScroll={event => { const scroll = event.currentTarget.scrollTop; setViewport(previous => ({...previous, scroll})); }} className={cn("nowheel nodrag relative min-h-0 overflow-y-auto px-2 pb-2", fixedHeight!==undefined && "flex-1")} style={fixedHeight===undefined ? {maxHeight: SHOWN_ROWS * ROW_HEIGHT + 8} : undefined}>
      {data.columns.map(column => <div key={column.name} className="relative flex h-8 items-center" style={{opacity:data.selected.size&&!data.selected.has(column.selection??`${data.selection}:${column.name}`)?0.3:1}} data-port={column.name}>
        <Button size="sm" variant="ghost" className={cn("relative !h-8 min-h-8 w-full justify-start text-left", data.selected.has(column.selection ?? `${data.selection}:${column.name}`) && "ring-2 ring-accent")} onClick={() => data.onSelect(column.selection ?? `${data.selection}:${column.name}`)}><span className="grid min-w-0 flex-1 text-left" title={column.logic ? `${column.name}\n${logicLabel}: ${column.logic}` : column.name}><span className="truncate">{column.name.split(".").slice(data.kind==="source"||data.kind==="target" ? -1 : -2).join(".")}</span>{column.logic ? <span className="truncate text-xs font-normal leading-3 text-muted">{column.logic}</span> : null}</span>{column.logic ? <MappingLogicMark kind={data.kind}/> : null}{column.detail ? <span className="max-w-[45%] truncate bg-surface text-muted" title={column.detail}>{column.detail}</span> : null}</Button>
      </div>)}
    </div>
    {data.description && data.kind==="write" ? <><button aria-expanded={engine} className="nodrag nopan w-full px-2 py-1 text-left text-xs text-muted focus-visible:outline-2 focus-visible:outline-ring" onClick={()=>setEngine(!engine)}>{`Engine columns (${data.description.split(",").length})`}</button>{engine ? <ul className="grid gap-1 px-2 pb-2 text-xs text-muted">{data.description.split(",").map(name=><li key={name}>{name.trim().toLowerCase()}</li>)}</ul> : null}</> : null}
  </DiagramNode></>;
}
type MappingEdge = Edge<{lane:number; obstacles:string[]; sentence:string}>;
function MappingLink(props: EdgeProps<MappingEdge>) {
  const flow = useReactFlow<Node<BoxData>,MappingEdge>();
  const obstacles = (props.data?.obstacles ?? []).flatMap(id => {
    const node = flow.getNode(id);
    return node ? [{x:node.position.x,y:node.position.y,width:node.measured?.width ?? (node.data.declared?(node.id.startsWith("source:")?320:256):160),height:node.measured?.height ?? (node.data.expanded ? HEADER_HEIGHT+Math.min(node.data.columns.length,SHOWN_ROWS)*ROW_HEIGHT+8 : 128)}] : [];
  });
  const points = mappingRoute({...props,lane:props.data?.lane ?? 0.5,obstacles});
  const first = points[1]!, last = points.at(-2)!;
  const middle: [number,number] = [(first[0]+last[0])/2,(first[1]+last[1])/2];
  return <DiagramEdge path={roundedMappingPath(points)} label={props.label} labelX={middle[0]} labelY={middle[1]} style={props.style} markerEnd={props.markerEnd} title={props.data?.sentence ?? "Declared table-level mapping"}/>;
}
const edgeTypes = {mapping:MappingLink};
const nodeTypes = { mapping: MappingBox };
const fitOptions = readableFit;

export function mappingLine(state: string) {
  return { label: state === "declared" ? "Declared" : undefined, style: { stroke: state === "declared" ? "var(--kind-out)" : "var(--accent)", strokeDasharray: state === "declared" ? "5 4" : undefined } };
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
  const frame = React.useRef<HTMLDivElement>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const flow=React.useRef<import("@xyflow/react").ReactFlowInstance<Node<BoxData>,Edge>|null>(null);
  React.useEffect(()=>{const element=frame.current;if(!element)return;const observer=new ResizeObserver(()=>requestAnimationFrame(()=>fitDiagram(flow.current,frame.current)));observer.observe(element);return()=>observer.disconnect();},[]);
  const [table, setTable] = React.useState(() => window.matchMedia("(max-width: 480px)").matches);
  const expansion = useDiagramExpansion(true);
  const [all, setAll] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [selected, setSelected] = React.useState<string | null>(null);
  const [positions, setPositions] = React.useState<Record<string, {x: number; y: number}>>({});
  const [sizes, setSizes] = React.useState<Record<string, NodeSize>>({});
  const resize = React.useCallback((id: string, size: NodeSize) => {
    setSizes(previous => ({ ...previous, [id]: size }));
  }, []);
  React.useEffect(()=>{
    const key=(event:KeyboardEvent)=>{
      if(event.key==="Escape")setSelected(null);
      if(event.key==="/" && !(event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement)){event.preventDefault();input.current?.focus();}
    };
    document.addEventListener("keydown",key);return()=>document.removeEventListener("keydown",key);
  },[]);
  const aliases = sourceAliases(task).filter(({alias,object,query})=>query || alias.toLowerCase()!==object.toLowerCase());
  const edges = task.mapping.edges;
  const targetTable = doc.tables.find(table => table.name === task.target);
  const declared = task.lineage.state === "declared";
  const unavailable = task.lineage.state === "unavailable";
  const paths = columnPaths(edges, selected, task.target);
  const tableRows = edges.length ? edges : declared && task.target && task.sources[0] ? [{ target_object: task.target, target_column: "(table)", source_object: task.sources[0], source_column: null, transformation: "declared", task: task.label }] : [];
  const query = search.toLowerCase();
  const matching = edges.filter(edge => `${edge.target_column} ${edge.source_column ?? ""}`.toLowerCase().includes(query));
  const visible = new Set(edges.filter(edge => matching.some(match => match.target_column === edge.target_column)).flatMap(edge => [`target:${task.target}:${edge.target_column}`, `source:${edge.source_object}:${edge.source_column}`]));
  const highlights = new Set<string>();
  paths.forEach(index => { const edge = edges[index]!; highlights.add(`target:${task.target}:${edge.target_column}`); highlights.add(`source:${edge.source_object}:${edge.source_column}`); });
  if(selected)highlights.add(selected);
  const nodes: Node<BoxData>[] = [];
  const lines: Edge[] = [];
  const activeEdges = edges.map((edge,index) => ({edge,index})).filter(({edge}) => !query || matching.some(match => match.target_column === edge.target_column));
  const rowset = !declared && task.sources.length > 0 && activeEdges.some(({edge}) => !edge.source_object || !edge.source_column);
  const fields = new Map<string,Port>();
  const fieldName = (edge: CatalogEdge) => edge.source_object && edge.source_column ? `${edge.source_object}.${edge.source_column}` : edge.target_column;
  activeEdges.filter(({edge}) => edge.source_object && edge.source_column).forEach(({edge}) => fields.set(fieldName(edge), {name:fieldName(edge),detail:"",selection:edge.source_object ? `source:${edge.source_object}:${edge.source_column}` : `target:${task.target}:${edge.target_column}`}));
  const fieldOrder = (port:Port) => {
    const edge = activeEdges.find(({edge}) => fieldName(edge) === port.name)?.edge;
    const source = doc.tables.find(table => table.name === edge?.source_object);
    return [sourcesForOrder.indexOf(edge?.source_object ?? port.name.slice(0,port.name.lastIndexOf("."))),Math.max(0,source?.columns.findIndex(column => column.name === (edge?.source_column??port.name.slice(port.name.lastIndexOf(".")+1))) ?? 0)];
  };
  task.mapping.steps.forEach(step=>(step.logic??[]).forEach(row=>mappingFields(task,row.columns,doc.tables).forEach(name=>{
    if(!fields.has(name))fields.set(name,{name,detail:"",selection:`source:${name.slice(0,name.lastIndexOf("."))}:${name.slice(name.lastIndexOf(".")+1)}`});
  })));
  const sourcesForOrder = task.sources;
  const orderedFields = [...fields.values()].sort((left,right) => { const a = fieldOrder(left), b = fieldOrder(right); return a[0]!-b[0]! || a[1]!-b[1]!; });
  const outputs = [...new Set(activeEdges.map(({edge}) => edge.target_column))].sort((left,right) => (targetTable?.columns.findIndex(column => column.name === left) ?? 0)-(targetTable?.columns.findIndex(column => column.name === right) ?? 0)).map(name => ({name,detail:"",selection:`target:${task.target}:${name}`}));
  const stages = task.mapping.steps.filter(step=>step.kind!=="source");
  const add = (id:string,title:string,x:number,y:number,columns:Port[],icon:LucideIcon,description?:string,conditions?:string[]) => {
    const open = expansion.isExpanded(id);
    nodes.push({id,type:"mapping",position:{x,y},dragHandle:".mapping-drag-handle",data:{selection:id,title,description,columns,icon,conditions,kind:id.startsWith("step:") ? stages[Number(id.slice(5))]!.kind : id.split(":")[0]!,declared,selected:selected ? highlights : new Set(),onSelect:setSelected,expanded:open,onExpanded:() => expansion.toggle(id),tableLevel:(declared && !edges.length) || (rowset && (id.startsWith("source:") || id.startsWith("step:") || (id==="expression" && activeEdges.some(({edge}) => !edge.source_column)))),size:sizes[id],onResize:(id,size)=>{setPositions(Object.fromEntries(nodes.map(node=>[node.id,node.position])));resize(id,size);}}});
  };
  const nodeHeight = (id: string, rows: number) => sizes[id]?.height ?? HEADER_HEIGHT + Math.min(rows, SHOWN_ROWS) * ROW_HEIGHT + 8;
  const sources = unavailable ? [] : task.sources;
  let sourceY = 0;
  sources.forEach(source => {
    const columns = doc.tables.find(table => table.name === source)?.columns ?? [];
    const used = new Set([...activeEdges.filter(({edge})=>edge.source_object===source).map(({edge})=>edge.source_column),...fields.keys()].map(name=>name?.startsWith(`${source}.`) ? name.slice(source.length+1) : name).filter(name=>name && !name.includes(".")));
    const names = new Set([...columns.filter(column => all || used.has(column.name)).map(column => column.name),...used].filter((name):name is string => !!name));
    const shown = [...names].filter(name => !query || visible.has(`source:${source}:${name}`) || name.toLowerCase().includes(query));
    add(`source:${source}`,source.replace(/^external:/,""),0,sourceY,shown.map(name => ({name,detail:columns.find(column => column.name === name)?.declared_type ?? "",input:false})),Database);
    sourceY += expansion.isExpanded(`source:${source}`) ? Math.max(160, nodeHeight(`source:${source}`, shown.length) + 40) : 160;
  });
  let x = sources.length ? declared ? 392 : 208 : 0;
  const relational: string[] = [];
  stages.forEach((step,index)=>{
    const id=`step:${index}`;relational.push(id);
    const rows=step.logic ?? [];
    const columns:Port[]=orderedFields.map(port=>({...port,logic:stageRows(task,rows,port.name,doc.tables).map(row=>row.label ? `${row.label}: ${row.expression}` : row.expression).join(" · ") || undefined}));
    rows.filter(row=>row.label==="Output").forEach(row=>columns.push({name:row.columns[0]!,detail:"",selection:`target:${task.target}:${row.columns[0]}`,logic:row.expression.replace(/^(.*) AS (\w+)$/i,"$2 = $1"),input:false}));
    add(id,stageLabel(step.kind),x,0,columns,({join:GitMerge,filter:Filter,aggregate:Sigma,set:Layers}[step.kind]??FunctionSquare),undefined,rows.filter(row=>row.label!=="Output"&&!mappingFields(task,row.columns,doc.tables).length).map(row=>row.expression));x+=208;
  });
  const expressions=[...new Set(activeEdges.filter(({edge})=>edge.transformation!=="copy"&&edge.transformation!=="declared"&&!/^(SUM|COUNT|AVG|MIN|MAX)\(/i.test(edge.transformation)).map(({edge})=>edge.target_column))];
  if(expressions.length){
    const ports:Port[]=[];
    const inputNames=[...new Set(activeEdges.filter(({edge})=>expressions.includes(edge.target_column)&&edge.source_object&&edge.source_column).map(({edge})=>fieldName(edge)))];
    ports.push(...inputNames.map(name=>({...fields.get(name)!,output:false})));
    expressions.forEach(name=>ports.push({name,detail:"",logic:`${name} = ${activeEdges.find(({edge})=>edge.target_column===name)!.edge.transformation}`,selection:`target:${task.target}:${name}`,input:false}));
    add("expression","Expression",x,0,ports,FunctionSquare);x+=208;
  }
  const ending:string[] = [];
  const rules = unavailable ? [] : doc.rules.filter(rule => rule.table === task.target && rule.type === "REJECT");
  if (rules.length) { add("rules","Rules",x,0,outputs.map(port=>({...port,logic:rules.flatMap(rule=>(rule.logic??[]).filter(row=>row.columns.length===1&&row.columns[0]!.split(".").at(-1)===port.name).map(row=>row.expression)).join(" · ") || undefined})),ShieldCheck,undefined,rules.flatMap(rule=>(rule.logic??[{expression:rule.sql,columns:[],label:""}]).filter(row=>row.columns.length!==1).map(row=>row.expression))); ending.push("rules"); x += expansion.isExpanded("rules") ? 208 : 208; }
  if (!unavailable && task.mapping.write.action) {
    const symbol = taskSymbol(task);
    add("write",symbol.label,x,0,outputs.map(port=>({...port,detail:(task.mapping.write.keys.MERGE_KEY??"").split(",").map(item=>item.trim()).includes(port.name) ? "Key" : (task.mapping.write.keys.MERGE_COMPARE_COLUMNS??"").split(",").map(item=>item.trim()).includes(port.name) ? "Compare" : ""})),symbol.icon,task.mapping.write.managed_columns.join(", "));
    ending.push("write"); x += expansion.isExpanded("write") ? 208 : 208;
  }
  if (task.target) {
    const columns = targetTable?.columns ?? [];
    add(`target:${task.target}`,task.target,x,0,columns.filter(column => (all || !edges.length || activeEdges.some(({edge}) => edge.target_column === column.name)) && (!query || visible.has(`target:${task.target}:${column.name}`) || column.name.toLowerCase().includes(query))).map(column => ({name:column.name,detail:[column.declared_type ?? column.data_type,column.declared_nullable==="N" ? "Not null" : column.declared_nullable==="Y" ? "Nullable" : null].filter(Boolean).join(" · "),output:false})),Database);
  }
  if (declared && !edges.length && task.target) sources.forEach(source => lines.push({id:`declared:${source}`,source:`source:${source}`,sourceHandle:"object",target:`target:${task.target}`,targetHandle:"object",...mappingLine("declared")}));
  if (rowset) {
    const computed = expressions.filter(column => activeEdges.some(({edge}) => edge.target_column === column && !edge.source_column));
    const active = !!selected && activeEdges.some(({edge,index}) => !edge.source_column && paths.has(index));
    const connectRows = (source:string,target:string) => {
      lines.push({id:`rows:${source}:${target}`,source,target,sourceHandle:"object",targetHandle:"object",label:"Rows",style:{stroke:active ? "var(--accent)" : "var(--muted)",strokeWidth:active ? 3 : 1,strokeDasharray:"2 4"}});
      if (active) { highlights.add(`${source}:object`); highlights.add(`${target}:object`); }
    };
    if (relational.length) {
      sources.forEach(source => connectRows(`source:${source}`,relational[0]!));
      relational.slice(1).forEach((step,index) => connectRows(relational[index]!,step));
      computed.forEach(() => connectRows(relational.at(-1)!,"expression"));
    } else sources.forEach(source => computed.forEach(() => connectRows(`source:${source}`,"expression")));
  }
  nodes.forEach(node => { node.position = positions[node.id] ?? node.position; });
  const nodeById = new Map(nodes.map(node=>[node.id,node]));
  if(selected)nodes.forEach(node=>{node.style={opacity:node.data.columns.some(port=>highlights.has(port.selection??`${node.id}:${port.name}`)) ? 1 : 0.3};});
  const open = (id:string) => nodeById.get(id)?.data.expanded;
  const routed = new Map<string,Edge>();
  stages.forEach((step,index)=>{
    const names=[...new Set((step.logic??[]).flatMap(row=>mappingFields(task,row.columns,doc.tables)))];
    names.forEach(name=>{
      if(activeEdges.some(({edge})=>fieldName(edge)===name))return;
      const dot=name.lastIndexOf(".");const source=`source:${name.slice(0,dot)}`;const column=name.slice(dot+1);
      if(!nodeById.has(source))return;
      const path=[source,...relational.slice(0,index+1)];
      path.slice(1).forEach((target,part)=>lines.push({id:`condition:${name}:${index}:${part}`,source:path[part]!,sourceHandle:part===0?column:name,target,targetHandle:name,style:{stroke:"var(--accent)",strokeDasharray:"2 4",opacity:selected ? 0.3 : 1}}));
    });
  });

  activeEdges.forEach(({edge,index}) => {
    if (!task.target) return;
    const field = fieldName(edge);
    const path: {id:string;input:string;output:string}[] = edge.source_object && edge.source_column ? [{id:`source:${edge.source_object}`,input:edge.source_column,output:edge.source_column}] : [];
    if(edge.source_object&&edge.source_column)path.push(...relational.map((id,index)=>{
      const stage=task.mapping.steps.filter(step=>step.kind!=="source")[index]!;
      const aggregate=stage.logic?.some(row=>row.label==="Output"&&row.columns.includes(edge.target_column));
      return {id,input:field,output:aggregate?edge.target_column:field};
    }));
    if(!edge.source_object||!edge.source_column){
      const aggregate=task.mapping.steps.filter(step=>step.kind!=="source").findIndex(step=>step.logic?.some(row=>row.label==="Output"&&row.columns.includes(edge.target_column)));
      if(aggregate>=0)path.push({id:`step:${aggregate}`,input:edge.target_column,output:edge.target_column});
    }
    if (expressions.includes(edge.target_column)) path.push({id:"expression",input:field,output:edge.target_column});
    path.push(...ending.map(id => ({id,input:edge.target_column,output:edge.target_column})),{id:`target:${task.target}`,input:edge.target_column,output:edge.target_column});
    const style = {...mappingLine(task.lineage.state).style,stroke:selected&&paths.has(index) ? "var(--accent)" : task.lineage.state==="declared" ? "var(--kind-out)" : "var(--accent)",strokeWidth:selected && paths.has(index) ? 2 : 1,opacity:selected && !paths.has(index) ? 0.3 : 1};
    path.slice(1).forEach((target,part) => {
      const source = path[part]!;
      const key = JSON.stringify([source.id,source.output,target.id,target.input]);
      const previous = routed.get(key);
      if (!previous || (selected && paths.has(index))) routed.set(key,{id:previous?.id ?? `${index}:${part}`,source:source.id,sourceHandle:source.output,target:target.id,targetHandle:target.input,label:mappingLine(task.lineage.state).label,style,type:open(source.id) && open(target.id) ? "straight" : "smoothstep"});
    });
  });
  lines.push(...routed.values());
  const groups = new Map<string,Edge[]>();
  lines.forEach(line => {
    const source = nodeById.get(line.source)!;
    const target = nodeById.get(line.target)!;
    const key = `${source.position.x}:${target.position.x}`;
    const group = groups.get(key) ?? []; group.push(line); groups.set(key,group);
  });
  groups.forEach(group => group.forEach((line,index) => {
    const source = nodeById.get(line.source)!;
    const target = nodeById.get(line.target)!;
    line.type = "mapping";
    line.data = {lane:(index+1)/(group.length+1),obstacles:nodes.filter(node => node.id!==source.id && node.id!==target.id).map(node => node.id),sentence:`${source.data.title}.${line.sourceHandle} → ${target.data.title}.${line.targetHandle}`};
    line.markerEnd = {type:MarkerType.ArrowClosed,color:line.style?.stroke ?? "var(--muted)",width:10,height:10,markerUnits:"userSpaceOnUse"};
  }));
  const conditions = nodes.find(node=>node.data.conditions?.length)?.data.conditions;
  const key=useLegend(unavailable?[]:[...nodes.map(node=>mappingStageEntry(node.data.kind,kindColor(node.data.kind),node.data.icon)),...nodes.filter(node=>node.data.columns.some(column=>column.logic)).map(node=>mappingLogicEntry(node.data.kind)),...(conditions?[{id:"stage-condition",group:"Conditions",name:"Stage condition",meaning:"Whole-stage logic not attached to one displayed field",sample:<MappingConditions conditions={conditions}/>}]:[]),{id:declared?"declared":"derived",group:"Lineage",name:declared?"Declared":"Derived",meaning:declared?"Documented by the developer; not verified":"Traced from the managed SELECT",sample:<svg width="36" height="12"><path d="M 0 6 H 36" style={mappingLine(task.lineage.state).style}/></svg>},...(selected&&paths.size?[highlightedEntry]:[]),...(nodes.some(node=>node.data.columns.some(column=>column.detail==="Key"))?[{id:"key",group:"Markers",name:"Key column",meaning:"Matches target rows when merging",sample:<span>Key</span>}]:[]),...(nodes.some(node=>node.data.columns.some(column=>column.detail==="Compare"))?[{id:"compare",group:"Markers",name:"Compare column",meaning:"Compared with the stored row to detect a changed value",sample:<span>Compare</span>}]:[]),...(task.mapping.steps.some(step=>step.logic?.some(row=>row.label==="Group by"))?[{id:"group",group:"Markers",name:"Group by",meaning:"Grouping column",sample:<span>Group by:</span>}]:[]),...["Y","N"].filter(value=>nodes.some(node=>node.id.startsWith("target:")&&node.data.columns.some(column=>column.detail.includes(value==="Y"?"Nullable":"Not null")))).map(value=>({id:`nullable:${value}`,group:"Markers",name:value==="Y"?"Nullable":"Not null",meaning:value==="Y"?"The target accepts NULL":"The target requires a value",sample:<span>{value==="Y"?"Nullable":"Not null"}</span>}))]);
  if(unavailable)return <div><p role="note" className="py-4 text-sm text-muted">{task.lineage.reason}</p>{task.target ? <Link className="text-sm text-accent" to={catalogPath(doc.project,"tables",task.target)}>Open {task.target}</Link> : null}</div>;
  const logicRows=task.mapping.steps.flatMap(step=>(step.logic??[]).map(row=>({target:row.label==="Output"?row.columns[0]??"":"",source:stageLabel(step.kind),logic:row.expression,provenance:"Derived"})));
  return <div ref={frame} onKeyDown={event=>{key.onKeyDown(event);if(!event.defaultPrevented)diagramKeys(event,()=>setSelected(null));}} className="grid min-w-0 gap-2 @3xl:flex @3xl:min-h-0 @3xl:flex-1 @3xl:flex-col">
    {declared ? <p role="note" className="py-1 text-sm text-muted">The engine doesn't verify declared lineage against the script.</p> : null}
    <DiagramToolbar zoomIn={!table?()=>void flow.current?.zoomIn():undefined} zoomOut={()=>void flow.current?.zoomOut()} fit={()=>fitDiagram(flow.current,frame.current,true)} reset={()=>void flow.current?.zoomTo(1)}><label className="flex min-w-0 items-center gap-2 text-xs"><span className="sr-only">Find a column</span><input ref={input} aria-label="Find a column" placeholder="Find a column" value={search} onChange={event=>setSearch(event.target.value)} className="h-control w-40 min-w-0 rounded-sm border border-border bg-surface px-2 focus-visible:outline-2 focus-visible:outline-ring"/></label><Button onClick={()=>setTable(!table)}>{table ? "Diagram" : "Table view"}</Button>{!table ? <><Button onClick={()=>setAll(!all)}>{all ? "Used columns" : "Show all columns"}</Button><Button onClick={expansion.toggleAll}>{expansion.expanded ? "Collapse all" : "Expand all"}</Button></> : null}<CatalogWidthButton/>{!table?key.button:null}</DiagramToolbar>
    {!table ? <p className="m-0 text-xs text-muted">Drag headers to move boxes; drag the background to pan. Resize from the edges or corners.</p> : null}
    {selected && !paths.size ? <p role="status" className="m-0 text-xs text-muted">No output-column path is recorded for {selected.replace(/^(source|target):/,"").replace(/:([^:]*)$/,".$1")}.</p> : null}
    {aliases.length ? <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted" aria-label="SQL source aliases"><span className="font-medium">SQL source aliases:</span>{aliases.map(({alias,object,query})=>query ? <details key={`${alias}:${object}:${query}`} className="min-w-0 max-w-full"><summary className="cursor-pointer"><code>{alias} = derived query</code></summary><pre tabIndex={0} aria-label={`Derived query ${alias}`} className="my-2 max-h-48 overflow-auto whitespace-pre-wrap break-all border border-border bg-surface-2 p-3 font-mono text-xs text-fg">{query}</pre></details> : <span key={`${alias}:${object}`} className="break-all"><code>{alias} = {object}</code></span>)}</div> : null}
    {table ? <div className="mapping-table" aria-label="Scrollable mapping table" tabIndex={0}><DataTable label="Task mapping" data={[
      ...(edges.length ? activeEdges.map(({edge})=>edge) : tableRows).map(edge=>({target:edge.target_column,source:edge.source_object ? `${edge.source_object.replace(/^external:/,"")}.${edge.source_column??""}` : "No direct source column",logic:edge.transformation==="copy" ? "Copy" : edge.transformation==="declared" ? "Declared" : edge.transformation,provenance:declared ? "Declared" : "Derived"})),
      ...logicRows,...rules.flatMap(rule=>(rule.logic??[{expression:rule.sql,columns:[],label:""}]).map(row=>({target:"",source:"Rules",logic:row.expression,provenance:"Derived"}))),
    ]} nextStep="Select a column in the diagram to follow its path." columns={columnsOf<{target:string;source:string;logic:string;provenance:string}>([{id:"target",header:"Target",size:160,value:row=>row.target},{id:"source",header:"Source",size:200,value:row=>row.source},{id:"logic",header:"Logic",size:240,value:row=>row.logic},{id:"provenance",header:"Provenance",size:120,value:row=>row.provenance}])}/></div>
 : nodes.length ? <div className="relative h-[70dvh] min-h-80 min-w-0 overflow-hidden rounded-sm border border-border @3xl:h-auto @3xl:min-h-0 @3xl:flex-1" aria-label="Task mapping diagram" tabIndex={0}><ReactFlow nodes={nodes} edges={lines} edgeTypes={edgeTypes} nodeTypes={nodeTypes} onInit={instance=>{flow.current=instance;requestAnimationFrame(()=>fitDiagram(instance,frame.current));}} onPaneClick={()=>setSelected(null)} fitView={false} fitViewOptions={fitOptions} minZoom={0.05} maxZoom={2} nodesDraggable nodesConnectable={false} onNodesChange={changes=>{const moved=changes.flatMap(change=>change.type==="position" && change.position ? [[change.id,change.position] as const] : []);if(moved.length)setPositions(previous=>({...previous,...Object.fromEntries(moved)}));}} proOptions={{ hideAttribution: true }}><Background /></ReactFlow>{key.panel}</div> : null}
  </div>;
}
