import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useActionReason } from "@/components/action-reason";
import { cn } from "@/lib/utils";

/** Page tabs keep their address, keyboard selection and scrolling within the same strip. */
export function Tabs({ tabs, value, onChange, className }: { tabs: Tab[]; value: string; onChange: (id: string) => void; className?: string }) {
  const strip = React.useRef<HTMLDivElement>(null);
  const [edges,setEdges] = React.useState({before:false,after:false});
  const measure = React.useCallback(() => {
    const element=strip.current;
    if(!element)return;
    const before=element.scrollLeft>1,after=element.scrollLeft+element.clientWidth<element.scrollWidth-1;
    setEdges(previous=>previous.before===before&&previous.after===after ? previous : {before,after});
  },[]);
  React.useLayoutEffect(()=>{
    measure();const element=strip.current;if(!element)return;
    const observer=new ResizeObserver(measure);observer.observe(element);
    return()=>observer.disconnect();
  },[measure,tabs]);
  const move=(event:React.KeyboardEvent,index:number)=>{
    const next=event.key==="Home" ? 0 : event.key==="End" ? tabs.length-1 : event.key==="ArrowRight" ? (index+1)%tabs.length : event.key==="ArrowLeft" ? (index+tabs.length-1)%tabs.length : null;
    if(next===null)return;
    event.preventDefault();
    if (!tabs[next]!.unavailableReason) onChange(tabs[next]!.id);
    strip.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  };
  return (
    <div className="relative min-w-0 max-w-full shrink-0">
    <div ref={strip} role="tablist" onScroll={measure} className={cn("flex min-w-0 max-w-full shrink-0 gap-1 overflow-x-auto overscroll-x-contain touch-pan-x border-b border-border [scroll-padding-inline:1rem]", className)}>
      {tabs.map((tab, index) => (
        <TabButton key={tab.id} tab={tab} selected={tab.id === value}
          tabIndex={tab.id === value || (!tabs.some((entry) => entry.id === value) && index === 0) ? 0 : -1}
          onMove={(event) => move(event, index)} onSelect={() => onChange(tab.id)} />
      ))}
    </div>
    {edges.before ? <span data-testid="tabs-scroll-start" aria-hidden className="pointer-events-none absolute inset-y-0 left-0 flex w-4 items-center bg-surface text-muted"><ChevronLeft className="size-3"/></span> : null}
    {edges.after ? <span data-testid="tabs-scroll-end" aria-hidden className="pointer-events-none absolute inset-y-0 right-0 flex w-4 items-center justify-end bg-surface text-muted"><ChevronRight className="size-3"/></span> : null}
    </div>
  );
}

type Tab = { id: string; label: string; unavailableReason?: string };

function TabButton({ tab, selected, tabIndex, onMove, onSelect }: {
  tab: Tab;
  selected: boolean;
  tabIndex: number;
  onMove: (event: React.KeyboardEvent) => void;
  onSelect: () => void;
}) {
  const { anchor, annotation, show } = useActionReason(tab.unavailableReason);
  return (
    <>
      <button
        type="button" role="tab" id={`tab-${tab.id}`} aria-selected={selected} aria-controls="tabpanel"
        aria-disabled={!!tab.unavailableReason || undefined} tabIndex={tabIndex}
        {...anchor}
        onKeyDown={(event) => { anchor.onKeyDown?.(event); onMove(event); }}
        onClick={(event) => { if (tab.unavailableReason) show(event); else onSelect(); }}
        onFocus={(event) => {
          event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
          anchor.onFocus?.(event);
        }}
        className={cn("-mb-px shrink-0 cursor-pointer border-b-2 px-3 py-2 text-sm font-medium aria-disabled:cursor-default", selected ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg")}
      >{tab.label}</button>
      {annotation}
    </>
  );
}
