import {describe,expect,it,vi} from "vitest";
import type {Edge,Node,ReactFlowInstance} from "@xyflow/react";
import {fitDiagram} from "@/lib/diagram-viewport";

/** A canvas of the given width inside a frame, and an instance whose nodes carry no size of their own. */
function setup(paneWidth:number,measured:{x:number;y:number;width:number;height:number}) {
  const frame=document.createElement("div");
  const canvas=document.createElement("div");canvas.className="react-flow";frame.append(canvas);
  canvas.getBoundingClientRect=()=>({width:paneWidth,height:300} as DOMRect);
  const nodes=[{id:"a",position:{x:0,y:0},data:{}},{id:"b",position:{x:300,y:0},data:{}}] as Node[];
  const instance={getNodes:()=>nodes,getNodesBounds:vi.fn(()=>measured),setViewport:vi.fn()};
  return {frame,instance:instance as unknown as ReactFlowInstance<Node,Edge>,calls:instance};
}

describe("fitDiagram",()=>{
  it("starts a diagram wider than its pane at its sources, using the measured sizes",()=>{
    const {frame,instance,calls}=setup(390,{x:0,y:0,width:530,height:52});
    fitDiagram(instance,frame);
    expect(calls.setViewport).toHaveBeenCalledWith({x:24,y:24,zoom:1});
  });
  it("fits a diagram that has room",()=>{
    const {frame,instance,calls}=setup(900,{x:0,y:0,width:530,height:52});
    fitDiagram(instance,frame);
    expect(calls.setViewport).toHaveBeenCalledWith({x:185,y:124,zoom:1});
  });
});

it("fits the complete measured diagram when explicitly requested",()=>{
 const {frame,instance,calls}=setup(390,{x:0,y:0,width:1600,height:600});
 fitDiagram(instance,frame,0.05);
 const [viewport]=calls.setViewport.mock.calls[0]!;
 expect(viewport.zoom).toBeLessThan(1);
 expect(viewport.x).toBeGreaterThan(0);
 expect(viewport.x+1600*viewport.zoom).toBeLessThan(390);
});
