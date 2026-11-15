import type {ReactFlowInstance,Node,Edge} from "@xyflow/react";

export const readableFit={padding:0.08,minZoom:1,maxZoom:1};
/** Start at readable size; an explicit whole-diagram request may zoom out to fit. */
export function fitDiagram<N extends Node,E extends Edge>(instance:ReactFlowInstance<N,E>|null,frame:HTMLElement|null,whole=false) {
  if(!instance||!frame)return;
  const canvas=frame.matches('.react-flow')?frame:frame.querySelector('.react-flow');
  if(!canvas)return;
  const nodes=instance.getNodes();if(!nodes.length)return;
  if(whole){void instance.fitView({...readableFit,minZoom:0.05});return;}
  // The instance reads the measured sizes; the standalone helper sees unmeasured nodes as zero wide.
  const bounds=instance.getNodesBounds(nodes);
  const pane=canvas.getBoundingClientRect();
  if(bounds.width+48>pane.width||bounds.height+48>pane.height)void instance.setViewport({x:24-bounds.x,y:24-bounds.y,zoom:1});
  else void instance.fitView(readableFit);
}
