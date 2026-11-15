import * as React from "react";
import {Background,MarkerType,ReactFlow,type Node,type Edge,type ReactFlowInstance} from "@xyflow/react";
import {ArrowUpRight,Database} from "lucide-react";
import {Link} from "react-router-dom";
import {MappingBox,MappingLink,SHOWN_ROWS,ROW_HEIGHT,HEADER_HEIGHT,type BoxData,type NodeSize} from "@/components/mapping-node";
import {DiagramToolbar} from "@/components/diagram-toolbar";
import {diagramKeys,useDiagramExpansion} from "@/components/diagram-node";
import {CatalogWidthButton} from "@/components/catalog-width";
import {Button} from "@/components/ui/button";
import {useLegend} from "@/components/legend";
import {highlightedEntry} from "@/components/diagram-key";
import {fitDiagram} from "@/lib/diagram-viewport";
import {tableLineage,type CatalogDoc} from "@/lib/catalog";
import {catalogPath} from "@/lib/routes";

const nodeTypes={mapping:MappingBox};
const edgeTypes={mapping:MappingLink};

/** Object and column views share the recorded catalog edges and the mapping node renderer. */
export function TableLineage({doc,name,depth,direction}:{doc:CatalogDoc;name:string;depth:number;direction:"both"|"up"|"down"}) {
 const frame=React.useRef<HTMLDivElement>(null);
 const flow=React.useRef<ReactFlowInstance<Node<BoxData>,Edge>|null>(null);
 const expansion=useDiagramExpansion(false);
 const [selected,setSelected]=React.useState<string|null>(null);
 const [positions,setPositions]=React.useState<Record<string,{x:number;y:number}>>({});
 const [sizes,setSizes]=React.useState<Record<string,NodeSize>>({});
 const graph=tableLineage(doc,name,depth,direction);
 const names=new Set(graph.waves.flat());
 const columns=doc.column_edges.filter(edge=>names.has(edge.source_object??"")&&names.has(edge.target_object)&&edge.source_column);
 const highlighted=new Set<string>(selected?[selected]:[]);
 const paths=new Set<number>();
 if(selected){
  for(const direction of ["up","down"]){
   const visited=new Set([selected]);let frontier=[selected];
   while(frontier.length){
    const next:string[]=[];
    columns.forEach((edge,index)=>{
     const source=`${edge.source_object}:${edge.source_column}`,target=`${edge.target_object}:${edge.target_column}`;
     const from=direction==="up"?target:source,to=direction==="up"?source:target;
     if(frontier.includes(from)){
      paths.add(index);highlighted.add(to);
      if(!visited.has(to)){visited.add(to);next.push(to);}
     }
    });
    frontier=next;
   }
  }
 }
 const nodes:Node<BoxData>[]=[];
 graph.waves.forEach((wave,x)=>{
  let y=0;
  wave.forEach(object=>{
   const fields=[...new Set([...(doc.tables.find(table=>table.name===object)?.columns.map(column=>column.name)??[]),...columns.flatMap(edge=>[...(edge.source_object===object?[edge.source_column!]:[]),...(edge.target_object===object?[edge.target_column]:[])])])];
   const expanded=expansion.isExpanded(object);
   nodes.push({id:object,type:"mapping",dragHandle:".mapping-drag-handle",position:positions[object]??{x:x*320,y},data:{selection:object,title:object.replace(/^external:/,""),columns:fields.map(field=>({name:field,detail:"",selection:`${object}:${field}`})),declared:false,selected:highlighted,onSelect:port=>setSelected(port===selected?null:port),expanded,onExpanded:()=>expansion.toggle(object),tableLevel:true,kind:object===name?"target":"source",icon:Database,size:sizes[object]??{width:240},onResize:(id,size)=>{setPositions(Object.fromEntries(nodes.map(node=>[node.id,node.position])));setSizes(previous=>({...previous,[id]:size}));},action:doc.tables.some(table=>table.name===object)?<Link aria-label={`Open ${object} details`} title="Open table details" className="nodrag nopan grid size-6 shrink-0 place-items-center border border-border-strong text-muted" to={catalogPath(doc.project,"tables",object)}><ArrowUpRight aria-hidden className="size-3"/></Link>:undefined}});
   y+=(expanded?(sizes[object]?.height??HEADER_HEIGHT+Math.min(fields.length,SHOWN_ROWS)*ROW_HEIGHT+8):HEADER_HEIGHT)+48;
  });
 });
 const edges:Edge[]=[];
 [...new Map(doc.table_edges.filter(edge=>names.has(edge.source)&&names.has(edge.target)).map(edge=>[`${edge.source}:${edge.target}`,edge])).values()].forEach((edge,index)=>{
  const recorded=columns.map((column,index)=>({column,index})).filter(({column})=>column.source_object===edge.source&&column.target_object===edge.target);
  const expanded=expansion.isExpanded(edge.source)||expansion.isExpanded(edge.target);
  if(expanded&&recorded.length){
   recorded.forEach(({column,index})=>{
    const on=paths.has(index);
    const declared=doc.tasks.find(task=>task.label===column.task)?.lineage.state==="declared";
    edges.push({id:`column:${index}`,source:edge.source,target:edge.target,sourceHandle:column.source_column??undefined,targetHandle:column.target_column,type:"mapping",style:{stroke:on?"var(--accent)":"var(--muted)",strokeWidth:on?2:1,opacity:selected&&!on?0.2:1,strokeDasharray:declared?"5 4":undefined},data:{lane:0.5,obstacles:nodes.filter(node=>node.id!==edge.source&&node.id!==edge.target).map(node=>node.id),sentence:`${column.source_object}.${column.source_column} → ${column.target_object}.${column.target_column}: ${column.transformation} (${column.task})`}});
   });
  }else edges.push({id:`table:${index}`,source:edge.source,target:edge.target,sourceHandle:"object",targetHandle:"object",type:"mapping",label:expanded?"No recorded column path":undefined,style:{stroke:"var(--muted)",strokeDasharray:expanded?"3 4":undefined},data:{lane:0.5,obstacles:[],sentence:`${edge.source} feeds ${edge.target}${recorded.length?"":"; no column path recorded"}`}});
 });
 edges.forEach(edge=>{edge.markerEnd={type:MarkerType.ArrowClosed,color:edge.style?.stroke,width:10,height:10,markerUnits:"userSpaceOnUse"};});
 const key=useLegend([...(nodes.some(node=>node.data.kind==="source")?[{id:"table",group:"Objects",name:"Related object",meaning:"An upstream or downstream table, view or external source",sample:<Database aria-hidden className="size-4" style={{color:"var(--kind-in)"}}/>}]:[]),{id:"current",group:"Objects",name:"Current object",meaning:"The table or view whose lineage is being explored",sample:<Database aria-hidden className="size-4" style={{color:"var(--kind-out)"}}/>},...(edges.some(edge=>edge.id.startsWith("table:"))?[{id:"object",group:"Lineage",name:"Object dependency",meaning:"A recorded source-to-target table relationship",sample:<svg width="36" height="12"><path d="M 0 6 H 36" stroke="var(--muted)"/></svg>}]:[]),...(edges.some(edge=>edge.id.startsWith("column:"))?[{id:"column",group:"Lineage",name:"Column path",meaning:"Expand a table to follow its recorded column connections",sample:<svg width="36" height="12"><path d="M 0 6 H 36" stroke="var(--muted)"/></svg>}]:[]),...(edges.some(edge=>edge.style?.strokeDasharray==="5 4")?[{id:"declared",group:"Lineage",name:"Declared",meaning:"Documented by the developer; not verified against script code",sample:<svg width="36" height="12"><path d="M 0 6 H 36" stroke="var(--muted)" strokeDasharray="5 4"/></svg>}]:[]),...(edges.some(edge=>edge.label)?[{id:"unavailable",group:"Lineage",name:"No recorded column path",meaning:"The object relationship exists, but no column connection is recorded",sample:<svg width="36" height="12"><path d="M 0 6 H 36" stroke="var(--muted)" strokeDasharray="3 4"/></svg>}]:[]),...(selected&&paths.size?[highlightedEntry]:[])]);
 React.useEffect(()=>{
  const element=frame.current;if(!element)return;
  const observer=new ResizeObserver(()=>requestAnimationFrame(()=>fitDiagram(flow.current,element)));
  observer.observe(element);return()=>observer.disconnect();
 },[]);
 return <div role="group" aria-label="Lineage diagram" tabIndex={0} className="flex h-[70dvh] min-h-0 flex-1 flex-col @3xl:h-full" onKeyDown={event=>{key.onKeyDown(event);if(!event.defaultPrevented)diagramKeys(event,()=>setSelected(null));}}>
  <p className="m-0 px-3 py-1.5 text-xs text-muted">Expand tables to show columns; select a column to follow its recorded path. Drag headers to move boxes.</p>
  <DiagramToolbar zoomIn={()=>void flow.current?.zoomIn()} zoomOut={()=>void flow.current?.zoomOut()} fit={()=>fitDiagram(flow.current,frame.current,true)} reset={()=>void flow.current?.zoomTo(1)}><Button onClick={expansion.toggleAll}>{expansion.expanded?"Collapse all":"Expand all"}</Button><CatalogWidthButton/>{key.button}</DiagramToolbar>
  {selected&&!paths.size?<p role="status" className="m-0 text-xs text-muted">No column path is recorded for {selected.replace(/:([^:]*)$/,".$1")}.</p>:null}
  <div ref={frame} className="relative min-h-72 flex-1 @3xl:min-h-0"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} minZoom={0.05} maxZoom={2} nodesConnectable={false} onNodesChange={changes=>{const moved=changes.flatMap(change=>change.type==="position"&&change.position?[[change.id,change.position] as const]:[]);if(moved.length)setPositions(previous=>({...previous,...Object.fromEntries(moved)}));}} onInit={instance=>{flow.current=instance;requestAnimationFrame(()=>fitDiagram(instance,frame.current));}} onPaneClick={()=>setSelected(null)} proOptions={{hideAttribution:true}}><Background/></ReactFlow>{key.panel}</div>
 </div>;
}
