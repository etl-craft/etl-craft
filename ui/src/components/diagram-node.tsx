import { BaseEdge, EdgeLabelRenderer, type Edge } from "@xyflow/react";
import * as React from "react";
import { ChevronDown, ChevronRight, MoreHorizontal, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownTrigger, DropdownContent, DropdownItem, DropdownLabel } from "@/components/dropdown";
import { AppLink } from "@/components/navigation";
import { useHref } from "react-router-dom";
import { openNavigationTab } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export type DiagramDetails = { to: string };

export type DiagramConnection = Pick<Edge,"source"|"target">;
export function isHighlightedConnection(edge:Edge) {
  return edge.domAttributes?.["aria-pressed"]===true;
}
export function sameConnection(left:DiagramConnection|null,right:DiagramConnection) {
  return left?.source===right.source && left.target===right.target;
}

/** Wires activate the same recorded-path selection with a mouse, touch or keyboard. */
export function connectionAction<E extends Edge>(edge:E,select:()=>void,active:boolean,label:string):E {
  return {...edge,selected:false,selectable:false,deletable:false,focusable:true,interactionWidth:24,ariaRole:"button",ariaLabel:`Highlight path: ${label}`,className:cn(edge.className,"diagram-connection"),
    style:{...edge.style,...(active?{stroke:"var(--accent)",strokeWidth:2.4,opacity:1}:{})},
    domAttributes:{...edge.domAttributes,"aria-pressed":active,"aria-describedby":undefined,"aria-description":"Highlight the connected columns or objects. Press Escape to clear.",
      onMouseDown:event=>event.preventDefault(),
      onClick:event=>{event.stopPropagation();event.currentTarget.focus({preventScroll:true});select();},
      onDoubleClick:event=>event.stopPropagation(),
      onKeyDown:event=>{if(event.key==="Escape"){event.preventDefault();event.stopPropagation();if(active)select();return;}if(event.key==="Enter"||event.key===" "){event.preventDefault();event.stopPropagation();event.currentTarget.focus({preventScroll:true});select();}},
    },
  };
}


/** The menu is the keyboard and touch path to catalog details; inspection stays in place. */
export function DiagramActions({ title, details, expanded, onExpanded, onInspect }: {title:string;details?:DiagramDetails;expanded:boolean;onExpanded:()=>void;onInspect?:()=>void}) {
  return <DropdownMenu>
    <DropdownTrigger asChild><Button size="icon" variant="ghost" aria-label={`Node actions for ${title}`} className="nodrag nopan shrink-0" onClick={event=>event.stopPropagation()} onDoubleClick={event=>event.stopPropagation()}><MoreHorizontal aria-hidden className="size-4"/></Button></DropdownTrigger>
    <DropdownContent onClick={event=>event.stopPropagation()} onKeyDown={event=>event.stopPropagation()}>
      {!details ? <DropdownLabel>No catalog entry for this node</DropdownLabel> : null}
      {details ? <DropdownItem asChild><AppLink to={details.to}>Open catalog details</AppLink></DropdownItem> : <DropdownItem disabled title="This node has no catalog entry">Open catalog details</DropdownItem>}
      <DropdownItem onSelect={onExpanded}>{expanded ? "Collapse" : "Expand"}</DropdownItem>
      {details ? <DropdownItem asChild><AppLink newTab to={details.to}>Open in new tab</AppLink></DropdownItem> : <DropdownItem disabled title="This node has no catalog entry">Open in new tab</DropdownItem>}
      {onInspect ? <DropdownItem onSelect={onInspect}>Inspect task</DropdownItem> : null}
    </DropdownContent>
  </DropdownMenu>;
}

/** Defer a mouse click until a double-click can cancel it; keyboard activation is immediate. */
export function useDiagramActivation(onExpand:()=>void, onOpen?:()=>void) {
  const pending=React.useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const pointer=React.useRef("mouse");
  const cancel=()=>{clearTimeout(pending.current);pending.current=undefined;};
  React.useEffect(()=>()=>clearTimeout(pending.current),[]);
  return {
    onPointerDown:(event:React.PointerEvent)=>{pointer.current=event.pointerType;},
    onClick:(event:React.MouseEvent)=>{
      event.stopPropagation();cancel();
      if(event.detail===0||pointer.current==="touch"){onExpand();return;}
      if(event.detail===1)pending.current=setTimeout(onExpand,500);
    },
    onDoubleClick:(event:React.MouseEvent)=>{event.stopPropagation();cancel();if(pointer.current==="mouse")onOpen?.();},
  };
}

/** The same compact header identifies pipeline tasks and column transformations. */
export function DiagramNode({title,tooltip,description,collapsedDescription,icon:Icon,expanded,onExpanded,children,collapsedPorts,details,onInspect,className,color="var(--muted)",chip,width=160,height,bodyClassName,tile=false}: {
  title:string;tooltip?:string;description?:React.ReactNode;collapsedDescription?:React.ReactNode;icon:LucideIcon;
  expanded:boolean;onExpanded:()=>void;children?:React.ReactNode;collapsedPorts?:React.ReactNode;
  details?:DiagramDetails;onInspect?:()=>void;headingClassName?:string;className?:string;color?:string;chip?:React.ReactNode;width?:number;
  height?:number;bodyClassName?:string;tile?:boolean;
}) {
  const href=useHref(details?.to??"/");
  const activation=useDiagramActivation(onExpanded,details ? ()=>openNavigationTab(href) : undefined);
  const collapsedTile=tile&&!expanded;
  return <div data-collapsed-tile={collapsedTile} data-expanded={expanded} className={cn("diagram-node relative w-40 text-[13px]",!collapsedTile&&"border border-border-strong bg-surface",height!==undefined&&"flex flex-col",className)} style={{width:collapsedTile?160:width,height,borderLeft:collapsedTile?undefined:`3px solid ${color}`}}>
    <div className="mapping-drag-handle flex h-10 shrink-0 items-center gap-1 px-2" style={{background:`color-mix(in srgb, ${color} 12%, transparent)`}}>
      <button type="button" className="nopan flex h-full min-w-0 flex-1 cursor-pointer items-center gap-2 text-left" title={tooltip??title} aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`} aria-expanded={expanded} {...activation}>
        <span className="diagram-object-icon" style={{color}}><Icon aria-hidden className="size-[18px] shrink-0"/></span>
        <strong className="min-w-0 flex-1 truncate font-medium" title={tooltip??title}>{title}</strong>
        {expanded ? <ChevronDown aria-hidden className="size-3 shrink-0"/> : <ChevronRight aria-hidden className="size-3 shrink-0"/>}
      </button>
      {chip}<DiagramActions title={title} details={details} expanded={expanded} onExpanded={onExpanded} onInspect={onInspect}/>
    </div>
    {expanded ? <div className={cn("diagram-body",bodyClassName)}>{description ? <div className="px-2 pb-1 text-xs text-muted">{description}</div> : null}{children}</div> : <>{collapsedDescription ? <div className="truncate px-2 pb-2 text-xs text-muted">{collapsedDescription}</div> : null}{collapsedPorts}</>}
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
  return <g><title>{title}</title><BaseEdge interactionWidth={24} path={path} style={style} markerEnd={markerEnd}/>{label ? <EdgeLabelRenderer><div title={title} className="nodrag nopan pointer-events-auto absolute whitespace-nowrap bg-surface text-xs" style={{transform:`translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`}}>{label}</div></EdgeLabelRenderer> : null}</g>;
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
