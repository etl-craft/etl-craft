import {useCallback,useRef} from "react";
import {getViewportForBounds,type Edge,type Node,type NodeChange,type OnMove,type ReactFlowInstance} from "@xyflow/react";

/** Keep wide diagrams readable and start at their sources. */
export function fitDiagram<N extends Node,E extends Edge>(instance:ReactFlowInstance<N,E>,frame:HTMLElement,minZoom=1) {
  const canvas=frame.querySelector(".react-flow");
  if(!canvas)return;
  const nodes=instance.getNodes();
  if(!nodes.length)return;
  const bounds=instance.getNodesBounds(nodes);
  const {width,height}=canvas.getBoundingClientRect();
  if(!width||!height)return;
  if(bounds.width*minZoom+48>width||bounds.height*minZoom+48>height){
    const first=nodes[0]!.position;
    return instance.setViewport({x:24-first.x*minZoom,y:24-first.y*minZoom,zoom:minZoom});
  }
  // React Flow's fitView queues a write for a later node update.
  return instance.setViewport(getViewportForBounds(bounds,width,height,minZoom,1,0.08));
}

/** Auto-fit measured layouts until the user takes control of the viewport. */
export function useDiagramViewport<N extends Node,E extends Edge>({fitZoom=0.05,refitOnMeasure=false}={}) {
  const flow=useRef<ReactFlowInstance<N,E>|null>(null);
  const frame=useRef<HTMLDivElement|null>(null);
  const moved=useRef(false);
  const pending=useRef(0);
  const scheduleFit=useCallback(()=>{
    if(moved.current||pending.current)return;
    pending.current=requestAnimationFrame(()=>{
      pending.current=0;
      const instance=flow.current;
      const element=frame.current;
      if(moved.current||!instance||!element)return;
      if(instance.getNodes().some(node=>{
        const measured=instance.getInternalNode(node.id)?.measured;
        return !measured?.width||!measured.height;
      }))return;
      void fitDiagram(instance,element)?.then(applied=>{
        if(applied&&frame.current===element&&!element.hasAttribute("data-fitted")){
          element.dataset.fitted="true";
        }
      });
    });
  },[]);
  const frameRef=useCallback((element:HTMLDivElement|null)=>{
    frame.current=element;
    if(!element)return;
    const observer=new ResizeObserver(scheduleFit);
    observer.observe(element);
    return ()=>{
      observer.disconnect();
      cancelAnimationFrame(pending.current);
      pending.current=0;
      frame.current=null;
    };
  },[scheduleFit]);
  const takeControl=useCallback(()=>{moved.current=true;},[]);
  const onMoveStart:OnMove=useCallback(event=>{if(event)takeControl();},[takeControl]);
  const onInit=useCallback((instance:ReactFlowInstance<N,E>)=>{
    flow.current=instance;
    scheduleFit();
  },[scheduleFit]);
  const onNodesChange=useCallback((changes:NodeChange<N>[])=>{
    // Mapping and lineage keep their canvas fixed while a user resizes a node.
    if(!refitOnMeasure&&frame.current?.hasAttribute("data-fitted"))return;
    if(changes.some(change=>change.type==="dimensions"))scheduleFit();
  },[refitOnMeasure,scheduleFit]);
  const toolbar={
    pan(dx:number,dy:number){
      takeControl();
      const instance=flow.current;
      if(!instance)return;
      const viewport=instance.getViewport();
      void instance.setViewport({...viewport,x:viewport.x-dx,y:viewport.y-dy});
    },
    zoomIn(){takeControl();void flow.current?.zoomIn();},
    zoomOut(){takeControl();void flow.current?.zoomOut();},
    fit(){takeControl();if(flow.current&&frame.current)void fitDiagram(flow.current,frame.current,fitZoom);},
    reset(){takeControl();void flow.current?.zoomTo(1);},
  };
  return {flow,frame,frameRef,scheduleFit,takeControl,onMoveStart,onInit,onNodesChange,toolbar};
}
