import * as React from "react";
import { ZoomIn, ZoomOut, Scan, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Aligned controls used by both definition and column diagrams. */
export function DiagramToolbar({children,zoomIn,zoomOut,fit,reset,className}: {children?:React.ReactNode;zoomIn?:()=>void;zoomOut?:()=>void;fit?:()=>void;reset?:()=>void;className?:string}) {
  return <div role="toolbar" aria-label="Diagram controls" className={cn("flex flex-wrap items-center gap-2 py-2",className)}>{children}{zoomIn ? <><Button size="icon" aria-label="Zoom in" onClick={zoomIn}><ZoomIn aria-hidden className="size-4"/></Button><Button size="icon" aria-label="Zoom out" onClick={zoomOut}><ZoomOut aria-hidden className="size-4"/></Button><Button size="icon" aria-label="Fit view" onClick={fit}><Scan aria-hidden className="size-4"/></Button><Button size="icon" aria-label="Reset zoom" onClick={reset}><RotateCcw aria-hidden className="size-4"/></Button></> : null}</div>;
}
export function DiagramChip({children,title}: {children:React.ReactNode;title?:string}) {return <span title={title} className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-surface-2 px-1.5 py-0.5 text-xs text-muted">{children}</span>;}
