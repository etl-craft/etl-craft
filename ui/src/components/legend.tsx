import * as React from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusMark, statusMeta } from "@/components/status";

export interface LegendEntry { id:string; group:string; name:string; meaning:string; sample:React.ReactNode }
export const LegendViewer = React.createContext("local");

const STATUS_MEANING:Record<string,string>={
  SUCCESS:"Finished without an error",FAILED:"Ended with an error",TIMED_OUT:"Ran past its time limit",
  "IN-PROGRESS":"Running now",RUNNING:"Running now",CLAIMED:"Claimed by an agent, about to start",
  QUEUED:"Waiting for a free slot",NOT_STARTED:"Has not started yet",SKIPPED:"Skipped on purpose",
  CANCELLED:"Stopped by a person",LOST:"The worker stopped reporting; the engine reconciles it",
  STOPPED:"Stopped before it finished",ABORTED:"Ended early by the engine",HELD:"Held until someone releases it",
  MET:"Finished within its SLA",BREACHED:"Missed its SLA",
};

export function statusEntries(statuses:Iterable<string>):LegendEntry[] {
  return [...new Set(statuses)].filter(Boolean).map(status=>({id:`status:${status}`,group:"Status",name:statusMeta(status).label,meaning:STATUS_MEANING[status]??"Status of a run or task",sample:<StatusMark status={status} solid/>}));
}

/** One floating key, with entries supplied by the view and preferences scoped to its viewer. */
export function useLegend(entries:LegendEntry[]) {
  const viewer=React.useContext(LegendViewer);
  const storage=`etl-craft-key:${viewer}`;
  const [open,setOpen]=React.useState(()=>{
    try{const kept=localStorage.getItem(storage);if(kept)return kept==="open";}catch{/* Storage is optional. */}
    return !window.matchMedia?.("(max-width: 480px)").matches;
  });
  const toggle=React.useRef<HTMLButtonElement>(null);
  const id=React.useId();
  const change=(value:boolean)=>{setOpen(value);try{localStorage.setItem(storage,value?"open":"closed");}catch{/* Storage is optional. */}};
  const close=()=>{change(false);toggle.current?.focus();};
  const onKeyDown=(event:React.KeyboardEvent)=>{
    if(event.key==="?"&&!(event.target instanceof HTMLElement&&/INPUT|TEXTAREA|SELECT/.test(event.target.tagName))){event.preventDefault();event.stopPropagation();change(!open);}
    if(event.key==="Escape"&&open){event.preventDefault();event.stopPropagation();close();}
  };
  const unique=[...new Map(entries.map(entry=>[entry.id,entry])).values()];
  return {onKeyDown,button:unique.length ? <Button ref={toggle} aria-expanded={open} aria-controls={id} onClick={()=>change(!open)}>Key</Button>:null,
    panel:unique.length ? <Legend id={id} open={open} entries={unique} onClose={close}/>:null};
}

export function Legend({id,open,entries,onClose}:{id:string;open:boolean;entries:LegendEntry[];onClose:()=>void}) {
  return <section id={id} hidden={!open} role="region" aria-label="View key" tabIndex={0} className="view-key">
    <header className="flex items-center justify-between gap-2 pb-2"><strong className="text-sm">Key</strong><Button size="icon" variant="ghost" aria-label="Close key" onClick={onClose}><X aria-hidden className="size-4"/></Button></header>
    {[...new Set(entries.map(entry=>entry.group))].map(group=><div key={group} className="mb-3 last:mb-0"><h3 className="mb-1 text-xs font-medium text-muted">{group}</h3><table className="w-full text-left text-xs"><tbody>{entries.filter(entry=>entry.group===group).map(entry=><tr key={entry.id}><td aria-hidden className="w-12 py-1 pr-2">{entry.sample}</td><th scope="row" className="whitespace-nowrap py-1 pr-3 font-medium">{entry.name}</th><td className="py-1 text-muted">{entry.meaning}</td></tr>)}</tbody></table></div>)}
  </section>;
}

/** Charts and dense matrices without diagram toolbars share the same key placement. */
export function LegendView({entries,children,className}:{entries:LegendEntry[];children:React.ReactNode;className?:string}) {
 const key=useLegend(entries);
 return <div className={`relative min-w-0 ${className??""}`} tabIndex={0} onKeyDown={key.onKeyDown}><div className="flex justify-end px-2 py-1">{key.button}</div>{children}{key.panel}</div>;
}
