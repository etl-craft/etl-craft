import * as React from "react";
import { ReactFlowProvider, useNodes, useReactFlow, useStore, useViewport, type Node, type NodeChange } from "@xyflow/react";
import { Scrollbar } from "@/components/scrollbar";
import { cn } from "@/lib/utils";

/** Application scroll tracks and canvas gestures control the same viewport. */
function DiagramScrollbars({id}:{id:string}) {
  const flow = useReactFlow();
  const nodes = useNodes();
  const { x, y, zoom } = useViewport();
  const width = useStore(state => state.width);
  const height = useStore(state => state.height);
  const bounds = flow.getNodesBounds(nodes);
  // A screen of space around the objects lets people move past their outermost edges.
  const left = Math.min(bounds.x * zoom - width, -x);
  const top = Math.min(bounds.y * zoom - height, -y);
  const right = Math.max((bounds.x + bounds.width) * zoom + width, -x + width);
  const bottom = Math.max((bounds.y + bounds.height) * zoom + height, -y + height);
  return <>
    <Scrollbar axis="horizontal" label="Diagram horizontal scrollbar" controls={id} className="diagram-scrollbar-horizontal" value={-x-left} maximum={Math.max(0,right-left-width)} page={width} onChange={offset=>{void flow.setViewport({...flow.getViewport(),x:-left-offset});}}/>
    <Scrollbar axis="vertical" label="Diagram vertical scrollbar" controls={id} className="diagram-scrollbar-vertical" value={-y-top} maximum={Math.max(0,bottom-top-height)} page={height} onChange={offset=>{void flow.setViewport({...flow.getViewport(),y:-top-offset});}}/>
    <span aria-hidden className="diagram-scrollbar-corner"/>
  </>;
}

/** A framed canvas reserves space for persistent scrollbars rather than covering its contents. */
export function DiagramFrame({ children, className, id:providedId, ...props }: React.ComponentProps<"div">) {
  const generatedId=React.useId();
  const id=providedId??generatedId;
  return <ReactFlowProvider><div id={id} {...props} className={cn("diagram-frame", className)}>{children}<DiagramScrollbars id={id}/></div></ReactFlowProvider>;
}

/** Controlled nodes retain measured handles when only selection or styling changes. */
export function useNodeMeasurements(nodes:Node[]) {
  const [sizes,setSizes]=React.useState<Record<string,{width:number;height:number}>>({});
  nodes.forEach(node=>{node.measured=sizes[node.id];});
  return React.useCallback((changes:NodeChange[])=>{
    const updates=changes.flatMap(change=>change.type==="dimensions"&&change.dimensions?[[change.id,change.dimensions] as const]:[]);
    if(updates.length)setSizes(previous=>updates.some(([id,size])=>previous[id]?.width!==size.width||previous[id]?.height!==size.height)?{...previous,...Object.fromEntries(updates)}:previous);
  },[]);
}
