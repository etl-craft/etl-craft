import * as React from "react";
import { ZoomIn, ZoomOut, Scan, RotateCcw, ArrowLeft, ArrowRight, ArrowUp, ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Aligned controls used by both definition and column diagrams. */
export function DiagramToolbar({children,zoomIn,zoomOut,fit,reset,pan,className}: {children?:React.ReactNode;zoomIn?:()=>void;zoomOut?:()=>void;fit?:()=>void;reset?:()=>void;pan?:(dx:number,dy:number)=>void;className?:string}) {
  return <div role="toolbar" aria-label="Diagram controls" className={cn("flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface-2 px-2 py-2",className)}>{children}{zoomIn ? <><Button size="icon" title="Zoom in" aria-label="Zoom in" onClick={zoomIn}><ZoomIn aria-hidden className="size-4"/></Button><Button size="icon" title="Zoom out" aria-label="Zoom out" onClick={zoomOut}><ZoomOut aria-hidden className="size-4"/></Button><Button size="icon" title="Fit view" aria-label="Fit view" onClick={fit}><Scan aria-hidden className="size-4"/></Button><Button size="icon" title="Reset zoom" aria-label="Reset zoom" onClick={reset}><RotateCcw aria-hidden className="size-4"/></Button></> : null}{pan ? <div role="group" aria-label="Move diagram view" className="flex gap-1">{([{label:"left",icon:ArrowLeft,dx:-120,dy:0},{label:"right",icon:ArrowRight,dx:120,dy:0},{label:"up",icon:ArrowUp,dx:0,dy:-120},{label:"down",icon:ArrowDown,dx:0,dy:120}]).map(({label,icon:Icon,dx,dy})=><Button key={label} size="icon" title={`Move view ${label}`} aria-label={`Move view ${label}`} onClick={()=>pan(dx,dy)}><Icon aria-hidden className="size-4"/></Button>)}</div> : null}</div>;
}
export function DiagramChip({children,title}: {children:React.ReactNode;title?:string}) {return <span title={title} className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-surface-2 px-1.5 py-0.5 text-xs text-muted">{children}</span>;}
