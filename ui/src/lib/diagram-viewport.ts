import type {ReactFlowInstance,Node,Edge} from "@xyflow/react";

export const readableFit={padding:0.08,minZoom:1,maxZoom:1};
/** Fit within the supplied readability floor; scrollbars reach any remaining objects. */
export function fitDiagram<N extends Node,E extends Edge>(instance:ReactFlowInstance<N,E>|null,frame:HTMLElement|null,minZoom=1) {
  if(!instance||!frame)return;
  const canvas=frame.matches('.react-flow')?frame:frame.querySelector('.react-flow');
  if(!canvas)return;
  const nodes=instance.getNodes();if(!nodes.length)return;
  // The instance reads the measured sizes; the standalone helper sees unmeasured nodes as zero wide.
  const bounds=instance.getNodesBounds(nodes);
  const pane=canvas.getBoundingClientRect();
  if(bounds.width*minZoom+48>pane.width||bounds.height*minZoom+48>pane.height){
    const first=nodes[0]!.position;
    void instance.setViewport({x:24-first.x*minZoom,y:24-first.y*minZoom,zoom:minZoom});
  }
  else void instance.fitView({...readableFit,minZoom});
}

/** Move the visible window in screen pixels while keeping the current zoom and node positions. */
export function panDiagram<N extends Node,E extends Edge>(instance:ReactFlowInstance<N,E>|null,dx:number,dy:number) {
  if(!instance)return;
  const viewport=instance.getViewport();
  void instance.setViewport({...viewport,x:viewport.x-dx,y:viewport.y-dy});
}
