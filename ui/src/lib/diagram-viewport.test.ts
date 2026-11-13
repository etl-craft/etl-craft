import {describe,expect,it,vi} from "vitest";
import type {Edge,Node,ReactFlowInstance} from "@xyflow/react";
import {fitDiagram} from "@/lib/diagram-viewport";

/** A canvas of the given width inside a frame, and an instance whose nodes carry no size of their own. */
function setup(paneWidth:number,measured:{x:number;y:number;width:number;height:number}) {
  const frame=document.createElement("div");
  const canvas=document.createElement("div");canvas.className="react-flow";frame.append(canvas);
  canvas.getBoundingClientRect=()=>({width:paneWidth,height:300} as DOMRect);
  const nodes=[{id:"a",position:{x:0,y:0},data:{}},{id:"b",position:{x:300,y:0},data:{}}] as Node[];
  const instance={getNodes:()=>nodes,getNodesBounds:vi.fn(()=>measured),setViewport:vi.fn(),fitView:vi.fn()};
  return {frame,instance:instance as unknown as ReactFlowInstance<Node,Edge>,calls:instance};
}

describe("fitDiagram",()=>{
  it("starts a diagram wider than its pane at its sources, using the measured sizes",()=>{
    const {frame,instance,calls}=setup(390,{x:0,y:0,width:530,height:52});
    fitDiagram(instance,frame);
    expect(calls.setViewport).toHaveBeenCalledWith({x:24,y:24,zoom:1});
    expect(calls.fitView).not.toHaveBeenCalled();
  });
  it("fits a diagram that has room",()=>{
    const {frame,instance,calls}=setup(900,{x:0,y:0,width:530,height:52});
    fitDiagram(instance,frame);
    expect(calls.fitView).toHaveBeenCalled();
    expect(calls.setViewport).not.toHaveBeenCalled();
  });
});
