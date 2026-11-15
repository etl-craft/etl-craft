import "@xyflow/react/dist/style.css";
import * as React from "react";
import {Handle,NodeResizer,useReactFlow,useUpdateNodeInternals,Position,type Node,type NodeProps,type Edge,type EdgeProps} from "@xyflow/react";
import type {LucideIcon} from "lucide-react";
import {MappingLogicMark,MappingConditions} from "@/components/diagram-key";
import {DiagramChip} from "@/components/diagram-toolbar";
import {DiagramNode,DiagramEdge} from "@/components/diagram-node";
import {kindColor,kindLabels} from "@/components/task-symbol";
import {Button} from "@/components/ui/button";
import {mappingRoute,roundedMappingPath} from "@/lib/mapping-arrows";
import {cn} from "@/lib/utils";

export type Port = { name: string; detail: string; logic?:string; selection?: string; input?: boolean; output?: boolean };
export type BoxData = { selection: string; title: string; description?: string; action?: React.ReactNode; columns: Port[]; declared: boolean; selected: Set<string>; onSelect: (name: string) => void; expanded: boolean; onExpanded: () => void; tableLevel?: boolean; kind:string; conditions?:string[]; icon: LucideIcon; size?: NodeSize; onResize: (id: string, size: NodeSize) => void } & Record<string, unknown>;
export type NodeSize = { width: number; height?: number };
/** A node lists this many column rows before its list scrolls; a resized node fills its height instead. */
export const SHOWN_ROWS = 5;
export const ROW_HEIGHT = 32;
export const HEADER_HEIGHT = 44;
export function MappingBox({ id, data }: NodeProps<Node<BoxData>>) {
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
  const objectPorts = data.tableLevel ? <>{!id.startsWith("source:") ? <Handle type="target" position={Position.Left} id="object" style={{top:expanded ? 48 : 20}}/> : null}{!id.startsWith("target:") && id!=="expression" ? <Handle type="source" position={Position.Right} id="object" style={{top:expanded ? 48 : 20}}/> : null}</> : null;
  const collapsedPorts = <>{data.columns.map(column => <React.Fragment key={column.name}>{column.input !== false ? <Handle type="target" position={Position.Left} id={column.name}/> : null}{column.output !== false ? <Handle type="source" position={Position.Right} id={column.name}/> : null}</React.Fragment>)}{objectPorts}</>;
  const size = data.size;
  const fixedHeight = size?.height;
  const logicLabel = kindLabels[data.kind] ?? "Logic";
  return <><NodeResizer minWidth={160} minHeight={HEADER_HEIGHT + ROW_HEIGHT * 2} onResize={(_, next) => data.onResize(id, { width: next.width, height: next.height })}/><DiagramNode title={data.title} action={data.action} width={size?.width ?? (data.declared?(id.startsWith("source:")?320:256):160)} height={fixedHeight} bodyClassName={fixedHeight!==undefined ? "flex min-h-0 flex-1 flex-col" : undefined} color={kindColor(data.kind)} chip={data.declared ? <DiagramChip>Declared</DiagramChip> : undefined} description={data.conditions?.length ? <MappingConditions conditions={data.conditions}/> : undefined} icon={data.icon} expanded={expanded} onExpanded={data.onExpanded} headingClassName="h-10" collapsedPorts={collapsedPorts} className={cn("mapping-node",data.declared && "border-dashed",data.selected.has(`${id}:object`) && "ring-2 ring-accent")}>
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
export function MappingLink(props: EdgeProps<MappingEdge>) {
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
