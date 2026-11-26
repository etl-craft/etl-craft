import { ScrollWindow } from "@/components/scrollbar";
import {DiagramFrame,useNodeMeasurements} from "@/components/diagram-frame";
import {useLegend,statusEntries} from "@/components/legend";
import {dependencyEntries,taskEntries,highlightedEntry,RunConditionMark} from "@/components/diagram-key";
import {DependencyBadge} from "@/components/dependency-mark";
import {Switch} from "@/components/switch";
import {useDiagramViewport} from "@/lib/diagram-viewport";
import { Box, CalendarClock, Play, Network, Hourglass, type LucideIcon } from "lucide-react";
import * as React from "react";
import { Background, Handle, MarkerType, Position, ReactFlow, getBezierPath, type EdgeProps, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { edgeClass, statusMeta, StatusBadge } from "@/components/status";
import { dependencyBadge, dependencyStyle, definitionLabel, dependencySentence } from "@/lib/catalog-flow";
import type { CatalogTask, DefinitionEdge } from "@/lib/catalog";
import type { Graph } from "@/lib/types";
import { diagramKeys, DiagramNode, DiagramEdge, useDiagramExpansion, connectionAction, isHighlightedConnection } from "@/components/diagram-node";
import { Button } from "@/components/ui/button";
import { DiagramToolbar, DiagramChip } from "@/components/diagram-toolbar";
import { kindColor } from "@/components/task-symbol";
import { taskSymbol } from "@/components/task-symbol";
import { cn } from "@/lib/utils";

type Focus = "none" | "focus" | "lineage" | "dim";

export type Direction = "LR" | "TB";

interface TaskData extends Record<string, unknown> {
  definition?: CatalogTask;
  catalogDetails?: string;
  inspectable?: boolean;
  upstreamCount?: number;
  symbol?: {icon:LucideIcon;label:string};
  expanded?: boolean;
  onExpanded?: () => void;
  label: string;
  tooltip?: string;
  width?: number;
  vertical: boolean;
  status: string;
  focus: Focus;
  blocked?: boolean;
  onOpen: (task: string) => void;
}
type TaskNode = Node<TaskData, "task">;

const WIDTH = 230;
const HEIGHT = 144;
const GAP_X = 70;
const GAP_Y = 24;
const MAX_ROWS = 4;
/** Top to bottom, a wave of many tasks wraps into rows of this many. */
const MAX_COLS = 3;
const GAP_ROW = 56;
const GAP_COL = 40;

const NODE_TONE: Record<Focus, string> = {
  none: "border-border-strong",
  focus: "border-accent ring-2 ring-accent",
  lineage: "border-accent",
  dim: "border-border opacity-40",
};

/** The kind prefix of an entry or exit box repeats its icon and subtitle, so the title is the name alone. */
function shownTitle(label: string, isTask: boolean): string {
  return isTask ? label : label.replace(/^(Schedule|Upstream|Downstream|Task gate): /, "");
}

function Task({ data }: NodeProps<TaskNode>) {
  const plain = data.status === "";
  const task = data.definition;
  const symbol = task ? taskSymbol(task) : data.symbol ?? {icon:Box,label:"Task"};
  const status = plain ? null : <StatusBadge status={data.status} quiet/>;
  const summary = <>{task?.active_flag==="N" ? <DiagramChip>Inactive</DiagramChip> : null}{task||data.symbol ? <span className="flex min-w-0 items-center justify-center gap-1"><span className="truncate" title={symbol.label}>{symbol.label}</span>{task ? <RunConditionMark task={task}/> : null}</span> : null}{status}{data.blocked ? <DiagramChip>Blocked by failure</DiagramChip> : null}</>;
  return <div data-focus={data.focus} className="relative" style={task?.active_flag === "N" ? {opacity:0.4} : undefined}>
    <Handle type="target" position={data.vertical ? Position.Top : Position.Left} className="!size-1.5 !border-0 !bg-border-strong"/>
    <DiagramNode bodyClassName="flex h-26 min-h-0 flex-col" tile={!data.symbol} title={shownTitle(data.label,Boolean(task)||!data.symbol)} tooltip={data.tooltip ?? data.label} width={data.width??WIDTH} color={task?kindColor(task.script_kind??task.handler):plain?"var(--muted)":`var(--${statusMeta(data.status).tone}-solid)`} icon={symbol.icon} collapsedDescription={summary} expanded={data.expanded ?? false} onExpanded={() => data.onExpanded?.()} details={data.catalogDetails ? {to:data.catalogDetails}:undefined} onInspect={data.inspectable ? ()=>data.onOpen(data.label) : undefined} description={<>{task?.active_flag==="N" ? <DiagramChip>Inactive</DiagramChip> : null}{task||data.symbol ? symbol.label : null}{status}</>} className={cn(NODE_TONE[data.focus], data.blocked && "border-bad", plain ? "border-l-border-strong" : edgeClass(data.status))}>
      <ScrollWindow className="min-h-0 flex-1"><div className="grid min-w-max gap-1 px-2 pb-2 text-xs">{task ? <><span className="whitespace-nowrap" title={task.target ?? undefined}>{task.target ?? "No target"}</span><span>Runs when: <RunConditionMark task={task}/></span></> : data.symbol ? <span>{data.label.startsWith("Schedule:") ? "Schedules and triggers admit this pipeline." : data.label.startsWith("Downstream:") ? "Open the downstream pipeline to inspect its tasks." : "This gate waits for its upstream dependency."}</span> : <span>Upstream tasks: {data.upstreamCount??0}</span>}</div></ScrollWindow>
    </DiagramNode>
    <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} className="!size-1.5 !border-0 !bg-border-strong"/>
  </div>;
}


const nodeTypes = { task: Task };
function DefinitionLink(props: EdgeProps) {
  const [path,labelX,labelY] = getBezierPath({...props,curvature:0.15});
  return <DiagramEdge path={path} label={props.label} labelX={labelX} labelY={labelY} style={props.style} markerEnd={props.markerEnd} title={String(props.data?.sentence ?? "")}/>;
}
const edgeTypes = { definition: DefinitionLink };

/** The task with everything upstream and downstream of it. */
export function lineageOf(graph: Graph, task: string): Set<string> {
  const downstream = new Map<string, string[]>();
  for (const [target, deps] of Object.entries(graph.depends_on))
    for (const [source] of deps) downstream.set(source, [...(downstream.get(source) ?? []), target]);
  const walk = (start: string, next: (id: string) => string[]) => {
    const seen = new Set<string>();
    const queue = [start];
    for (let id = queue.pop(); id !== undefined; id = queue.pop()) {
      for (const other of next(id)) {
        if (seen.has(other)) continue;
        seen.add(other);
        queue.push(other);
      }
    }
    return seen;
  };
  const up = walk(task, (id) => (graph.depends_on[id] ?? []).map(([source]) => source));
  const down = walk(task, (id) => downstream.get(id) ?? []);
  return new Set([task, ...up, ...down]);
}

/** One column per dependency wave; edges come from the pipeline's stored dependency rows. */
export function layout(
  graph: Graph,
  statuses: Record<string, string>,
  focused: string | null,
  onOpen: (task: string) => void = () => undefined,
  plain = false,
  direction: Direction = "LR",
): { nodes: TaskNode[]; edges: Edge[]; height: number } {
  const lineage = focused ? lineageOf(graph, focused) : null;
  const stateOf = (code: string): Focus => (!lineage ? "none" : code === focused ? "focus" : lineage.has(code) ? "lineage" : "dim");
  // A wave of many tasks wraps into extra columns; every column is centred on the tallest one.
  const vertical = direction === "TB";
  const per = vertical ? MAX_COLS : MAX_ROWS;
  const rowsOf = (wave: string[]) => Math.min(wave.length, per);
  const tallest = Math.max(1, ...graph.waves.map(rowsOf));
  let column = 0;
  const nodes: TaskNode[] = graph.waves.flatMap((wave) => {
    const lift = ((tallest - rowsOf(wave)) * (vertical ? WIDTH + GAP_COL : HEIGHT + GAP_Y)) / 2;
    const placed = wave.map((code, index) => ({
      id: code,
      type: "task" as const,
      position: vertical
        ? { x: lift + (index % per) * (WIDTH + GAP_COL), y: (column + Math.floor(index / per)) * (HEIGHT + GAP_ROW) }
        : { x: (column + Math.floor(index / per)) * (WIDTH + GAP_X), y: lift + (index % per) * (HEIGHT + GAP_Y) },
      data: { label: code, vertical, status: statuses[code] ?? (plain ? "" : "QUEUED"), focus: stateOf(code), onOpen },
      draggable: false,
    }));
    column += Math.max(1, Math.ceil(wave.length / per));
    return placed;
  });
  const edges: Edge[] = Object.entries(graph.depends_on).flatMap(([task, deps]) =>
    deps.map(([dependency, condition]) => {
      const on = lineage ? lineage.has(dependency) && lineage.has(task) : false;
      const color = on ? "var(--accent)" : "var(--muted)";
      return {
        id: `${dependency}->${task}`,
        source: dependency,
        target: task,
        label: condition ? dependencyBadge(condition) || undefined : undefined,
        style: {
          ...dependencyStyle(condition ?? "SUCCESS"),
          stroke: color,
          strokeWidth: on ? 2.4 : 1.6,
          opacity: lineage && !on ? 0.25 : 1,
        },
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color },
        labelBgStyle: { fill: "var(--surface)", stroke: "var(--border-strong)" },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 4,
        labelStyle: { fill: "var(--fg)", fontSize: 12, fontWeight: 500 },
      };
    }),
  );
  return { nodes, edges, height: Math.min(460, Math.max(200, tallest * (HEIGHT + GAP_Y) + 40)) };
}

export function RunGraph({
  graph,
  statuses,
  focused,
  onFocus,
  onOpen,
  plain,
  fill,
  direction,
  definition,
  catalogDetails,
  blocked,
}: {
  blocked?: string[];
  catalogDetails?: (node:string)=>string|null;
  definition?: { tasks: CatalogTask[]; edges: DefinitionEdge[]; overlay?:boolean; onOverlay?:()=>void; schedule?:string|null };
  graph: Graph;
  statuses: Record<string, string>;
  focused: string | null;
  onFocus: (task: string | null) => void;
  onOpen: (task: string) => void;
  /** Show task definitions only, with no run status. */
  plain?: boolean;
  /** Take the height of the container. */
  fill?: boolean;
  /** Left to right or top to bottom; when omitted a filled graph picks the one that suits its pane's shape. */
  direction?: Direction;
}) {
  const expansion = useDiagramExpansion(false);
  const {flow,frame,scheduleFit,frameRef,takeControl,onInit,onMoveStart,onNodesChange,toolbar}=useDiagramViewport<TaskNode,Edge>({fitZoom:definition?0.05:0.7,refitOnMeasure:true});
  const [width, setWidth] = React.useState(0);
  const [frameHeight, setFrameHeight] = React.useState(0);
  const [chromeHeight,setChromeHeight]=React.useState(0);
  React.useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry?.contentRect.width ?? 0);
      setFrameHeight(entry?.contentRect.height ?? 0);
      if(entry&&element.parentElement)setChromeHeight(Math.ceil(element.parentElement.clientHeight-entry.contentRect.height));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [frame]);
  const [wireFocus,setWireFocus]=React.useState<string|null|undefined>(undefined);
  const shown: Direction = direction ?? (definition ? "LR" : fill && frameHeight > width ? "TB" : "LR");
  const { nodes, edges, height } = layout(graph, statuses, focused, onOpen, plain, shown);
  const blockedTasks = new Set(blocked);
  nodes.forEach((node) => { node.data.blocked = blockedTasks.has(node.id); });
  nodes.forEach(node=>{node.data.upstreamCount=(graph.depends_on[node.id]??[]).length;node.data.inspectable=!definition;node.data.catalogDetails=catalogDetails?.(node.id)??undefined;node.data.expanded=expansion.isExpanded(node.id);node.data.onExpanded=()=>expansion.toggle(node.id);});
  let definitionHeight=280;
  if (definition) {
    nodes.forEach(node => { node.data.definition = definition.tasks.find(task => task.code === node.id || task.label === node.id); node.data.expanded = expansion.isExpanded(node.id); node.data.width=node.data.definition?176:Math.min(232,Math.max(176,shownTitle(node.data.label,false).length*7+104)); node.data.onExpanded = () => expansion.toggle(node.id); if (!node.data.definition) { node.data.status = ""; node.data.tooltip=node.id.startsWith("Schedule: ") ? definition.schedule??"Manual" : node.id; node.data.symbol = node.id.startsWith("Schedule: ") ? {icon:node.id.startsWith("Schedule: manual") ? Play : CalendarClock,label:"Schedule"} : node.id.startsWith("Downstream: ") ? {icon:Network,label:"Downstream pipeline"} : {icon:Hourglass,label:"Upstream gate"}; } });
    if (shown === "LR") {
      let x = 0;
      const groups = new Map<number,TaskNode[]>();
      nodes.forEach(node => { const group = groups.get(node.position.x) ?? []; group.push(node); groups.set(node.position.x,group); });
      [...groups.entries()].sort(([a],[b]) => a-b).forEach(([,group]) => {
        const width = Math.max(...group.map(node=>node.data.width??176));
        let y=0;
        group.sort((a,b)=>a.position.y-b.position.y).forEach(node=>{node.position.x=x;node.position.y=y;y+=HEIGHT+8;});
        x += width + 56;
      });
    }
    definitionHeight=Math.max(280,...nodes.map(node=>node.position.y+HEIGHT+32));
    edges.forEach(edge => {
      const item = definition.edges.find(item => (item.source.endsWith(`.${edge.source}`) && item.target.endsWith(`.${edge.target}`)) || (item.kind === "task" && edge.source.startsWith(`Task gate: ${item.source} ·`) && item.target.endsWith(`.${edge.target}`)) || (item.kind === "pipeline" && ((item.target === definition.tasks[0]?.pipeline && edge.source.startsWith(`Upstream: ${item.source} ·`)) || (item.source === definition.tasks[0]?.pipeline && edge.target === `Downstream: ${item.target}`)))) ?? { kind: "task" as const, source: edge.source, target: edge.target, dependency_type: graph.depends_on[edge.target]?.find(([source]) => source === edge.source)?.[1] ?? "SUCCESS", consume_repairs: "Y" };
      edge.type = "definition";
      edge.data = { definition:item, sentence: dependencySentence(item.source, item.target, item.dependency_type) };
      edge.style = { ...edge.style, ...dependencyStyle(item.dependency_type), stroke: edge.style?.stroke };
      edge.label = definitionLabel(item) ? <DependencyBadge edge={item} /> : undefined;
      edge.markerEnd = { type: MarkerType.ArrowClosed, color: edge.style?.stroke ?? "var(--muted)",width:10,height:10,markerUnits:"userSpaceOnUse" };
    });
  }
  edges.forEach(edge=>{
    const active=Boolean(focused)&&edge.style?.opacity!==0.25;
    Object.assign(edge,connectionAction(edge,()=>{const next=active?null:edge.target;setWireFocus(next);onFocus(next);},active,String(edge.data?.sentence??`${edge.source} → ${edge.target}`)));
  });
  const measureNodes=useNodeMeasurements(nodes);
  const key=useLegend([...dependencyEntries(plain&&!definition?[]:definition ? edges.map(edge=>edge.data?.definition as DefinitionEdge) : Object.values(graph.depends_on).flatMap(deps=>deps.map(([,kind])=>({dependency_type:kind})))),...(definition?taskEntries(definition.tasks):[]),...(!plain?statusEntries(Object.values(statuses)):[]),...(plain&&!definition?[{id:"lineage",group:"Lineage",name:"Table dependency",meaning:"The source table feeds the target table",sample:<svg width="36" height="12"><path d="M 0 6 H 36" stroke="var(--muted)"/></svg>}]:[]),...(edges.some(isHighlightedConnection)?[highlightedEntry]:[])]);
  // Bring a focused task into view when it is off-screen; leave the view alone when it is visible.
  React.useEffect(() => {
    if(wireFocus===focused)return;
    const instance = flow.current;
    const node = nodes.find((n) => n.id === focused);
    if (!instance || !node || width === 0) return;
    const { x, zoom } = instance.getViewport();
    const left = node.position.x * zoom + x;
    if (left >= 0 && left + WIDTH * zoom <= width) return;
    void instance.setCenter(node.position.x + (instance.getNode(node.id)?.measured?.width ?? WIDTH) / 2, node.position.y + (instance.getNode(node.id)?.measured?.height ?? HEIGHT) / 2, { zoom, duration: 250 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused,wireFocus]);
  React.useEffect(scheduleFit,[scheduleFit,shown]);
  return (
    <div style={definition ? {height:`min(70vh, ${definitionHeight+(chromeHeight||(width<480?204:124))}px)`} : fill ? undefined : { height }} role="group" aria-label="Task graph" tabIndex={0} onKeyDown={key.onKeyDown} className={cn("flex w-full flex-col", fill && "h-full min-h-0",fill && definition && "@3xl:!h-full")}>
      {/* The hint sits above the canvas, so a graph shown at a readable size never runs under it. */}
      <p className="m-0 shrink-0 px-3 py-1.5 text-xs text-muted">
        {edges.length === 0 ? "No dependencies between these tasks: they can run at the same time." : focused ? `Showing everything upstream and downstream of ${focused}. Click the background to clear.` : "Click an icon to expand; select a wire to highlight its path."}
      </p>
      <DiagramToolbar {...toolbar} className="px-3">{definition ? <><Switch checked={definition.overlay??false} onChange={()=>definition.onOverlay?.()} label="Show last-run status"/><Button onClick={expansion.toggleAll}>{expansion.expanded?"Collapse all":"Expand all"}</Button></>:null}{key.button}</DiagramToolbar>
      <DiagramFrame ref={frameRef} onViewportMove={takeControl} className="relative min-h-0 flex-1">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView={false}
        minZoom={0.05}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodesChange={changes=>{
          measureNodes(changes);
          onNodesChange(changes);
        }}
        elementsSelectable
        onNodeClick={(_, node) => onFocus(node.id === focused ? null : node.id)}
        onKeyDown={event=>{
          diagramKeys(event,()=>onFocus(null));
          if(event.key==="Enter"){
            const element=(event.target as HTMLElement).closest<HTMLElement>("[data-id]");
            if(element?.dataset.id)onFocus(element.dataset.id);
          }
        }}
        onInit={onInit}
        onMoveStart={onMoveStart}
        onPaneClick={() => onFocus(null)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} color="var(--border)" />

      </ReactFlow>
      {key.panel}</DiagramFrame>
    </div>
  );
}
