import * as React from "react";
import { ReactFlowProvider, useNodes, useReactFlow, useStore, useViewport, type Viewport, type Node, type NodeChange } from "@xyflow/react";
import { cn } from "@/lib/utils";

/** Native scroll tracks and canvas gestures control the same viewport. */
function DiagramScrollbars() {
  const flow = useReactFlow();
  const nodes = useNodes();
  const { x, y, zoom } = useViewport();
  const width = useStore(state => state.width);
  const height = useStore(state => state.height);
  const horizontal = React.useRef<HTMLDivElement>(null);
  const vertical = React.useRef<HTMLDivElement>(null);
  const synchronized = React.useRef({left: 0, top: 0});
  const intent = React.useRef(false);
  const nativeViewport = React.useRef<Viewport | null>(null);
  const bounds = flow.getNodesBounds(nodes);
  // A screen of space around the objects lets people move past their outermost edges.
  const left = Math.min(bounds.x * zoom - width, -x);
  const top = Math.min(bounds.y * zoom - height, -y);
  const right = Math.max((bounds.x + bounds.width) * zoom + width, -x + width);
  const bottom = Math.max((bounds.y + bounds.height) * zoom + height, -y + height);
  React.useLayoutEffect(() => {
    const native = nativeViewport.current;
    if (!native || Math.abs(x-native.x)>1 || Math.abs(y-native.y)>1 || zoom!==native.zoom) intent.current=false;
    nativeViewport.current=null;
    if (horizontal.current) {
      horizontal.current.scrollTo({left: -x - left, behavior: "instant"});
      synchronized.current.left = horizontal.current.scrollLeft;
    }
    if (vertical.current) {
      vertical.current.scrollTo({top: -y - top, behavior: "instant"});
      synchronized.current.top = vertical.current.scrollTop;
    }
  }, [x, y, zoom, left, top, right, bottom, width, height]);
  const markIntent=()=>{intent.current=true;};
  const input={onWheelCapture:markIntent,onPointerEnter:markIntent,onPointerDown:markIntent,onKeyDownCapture:markIntent,onFocus:markIntent};
  const scroll=(element:HTMLDivElement,axis:"x"|"y")=>{
    const key=axis==="x"?"left":"top";
    const offset=axis==="x"?element.scrollLeft:element.scrollTop;
    if(Math.abs(offset-synchronized.current[key])<1)return;
    // A new viewport command cancels queued native scrolling, including track-click animation.
    if(!intent.current){element.scrollTo({[key]:synchronized.current[key],behavior:"instant"});return;}
    synchronized.current[key]=offset;
    const viewport={...flow.getViewport(),[axis]:-(axis==="x"?left:top)-offset};
    nativeViewport.current=viewport;
    void flow.setViewport(viewport);
  };
  return <>
    <div {...input} ref={horizontal} tabIndex={0} role="region" aria-label="Diagram horizontal scrollbar" className="diagram-scrollbar diagram-scrollbar-horizontal nowheel nopan" onScroll={event=>scroll(event.currentTarget,"x")}><div style={{width:Math.max(width,right-left),height:1}}/></div>
    <div {...input} ref={vertical} tabIndex={0} role="region" aria-label="Diagram vertical scrollbar" className="diagram-scrollbar diagram-scrollbar-vertical nowheel nopan" onScroll={event=>scroll(event.currentTarget,"y")}><div style={{height:Math.max(height,bottom-top),width:1}}/></div>
    <span aria-hidden className="diagram-scrollbar-corner"/>
  </>;
}

/** A framed canvas reserves space for persistent scrollbars rather than covering its contents. */
export function DiagramFrame({ children, className, ...props }: React.ComponentProps<"div">) {
  return <ReactFlowProvider><div {...props} className={cn("diagram-frame", className)}>{children}<DiagramScrollbars/></div></ReactFlowProvider>;
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
