import { BaseEdge, EdgeLabelRenderer } from "@xyflow/react";
import * as React from "react";
import { ChevronDown, ChevronRight, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The same compact header identifies pipeline tasks and column transformations. */
export function DiagramNode({title,tooltip,description,collapsedDescription,icon:Icon,expanded,onExpanded,children,collapsedPorts,action,className,color="var(--muted)",chip,width=160}: {
  title:string;tooltip?:string;description?:React.ReactNode;collapsedDescription?:React.ReactNode;icon:LucideIcon;
  expanded:boolean;onExpanded:()=>void;children?:React.ReactNode;collapsedPorts?:React.ReactNode;
  action?:React.ReactNode;headingClassName?:string;className?:string;color?:string;chip?:React.ReactNode;width?:number;
}) {
  return <div className={cn("diagram-node relative w-40 rounded-sm border border-border bg-surface text-[13px]",className)} style={{width,borderLeft:`2px solid ${color}`}}>
    <div className="flex h-10 items-center gap-1 px-2">
      <Icon aria-hidden className="size-[18px] shrink-0" style={{color}}/>
      <strong className="min-w-0 flex-1 truncate font-medium" title={tooltip??title}>{title}</strong>
      {chip}{action}
      <Button size="icon" variant="ghost" className="nodrag nopan !size-6 shrink-0" aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`} aria-expanded={expanded} onClick={event=>{event.stopPropagation();onExpanded();}}>{expanded ? <ChevronDown aria-hidden className="size-3"/> : <ChevronRight aria-hidden className="size-3"/>}</Button>
    </div>
    {expanded ? <div className="diagram-body">{description ? <div className="px-2 pb-1 text-xs text-muted">{description}</div> : null}{children}</div> : <>{collapsedDescription ? <div className="truncate px-2 pb-2 text-xs text-muted">{collapsedDescription}</div> : null}{collapsedPorts}</>}
  </div>;
}

export function useDiagramExpansion(initial:boolean) {
  const [expanded,setExpanded]=React.useState(initial);
  const [exceptions,setExceptions]=React.useState<Set<string>>(new Set());
  const toggle=(id:string)=>setExceptions(previous=>{const next=new Set(previous);if(next.has(id))next.delete(id);else next.add(id);return next;});
  return {expanded,isExpanded:(id:string)=>expanded!==exceptions.has(id),toggle,toggleAll:()=>{setExpanded(previous=>!previous);setExceptions(new Set());}};
}

export function DiagramEdge({path,label,labelX,labelY,style,markerEnd,title}: {
  path:string;label?:React.ReactNode;labelX:number;labelY:number;style?:React.CSSProperties;markerEnd?:string;title:string;
}) {
  return <g><title>{title}</title><BaseEdge path={path} style={style} markerEnd={markerEnd}/>{label ? <EdgeLabelRenderer><div title={title} className="nodrag nopan pointer-events-auto absolute whitespace-nowrap bg-surface text-xs" style={{transform:`translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`}}>{label}</div></EdgeLabelRenderer> : null}</g>;
}

/** Arrow keys traverse diagram nodes; text inputs retain their native navigation. */
export function diagramKeys(event:React.KeyboardEvent,onEscape:()=>void) {
  if(event.key==="Escape"){onEscape();return;}
  if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)||event.target instanceof HTMLInputElement)return;
  const current=(event.target as HTMLElement).closest<HTMLElement>(".react-flow__node");
  if(!current)return;
  const nodes=[...event.currentTarget.querySelectorAll<HTMLElement>(".react-flow__node")];
  const index=nodes.indexOf(current),step=event.key==="ArrowLeft"||event.key==="ArrowUp"?-1:1;
  event.preventDefault();nodes[(index+step+nodes.length)%nodes.length]?.focus();
}
