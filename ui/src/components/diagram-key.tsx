import { Database, Filter, FunctionSquare, GitMerge, Sigma, ShieldCheck, type LucideIcon } from "lucide-react";
import {DiagramChip} from "@/components/diagram-toolbar";
import {DependencyBadge} from "@/components/dependency-mark";
import type {LegendEntry} from "@/components/legend";
import {dependencyStyle,dependencyBadge,runCondition} from "@/lib/catalog-flow";
import {taskSymbol,kindColor,kindLabels} from "@/components/task-symbol";
import type {CatalogTask} from "@/lib/catalog";

export function dependencyEntries(edges:{dependency_type:string;consume_repairs?:string}[]):LegendEntry[] {
 const rows=[...new Set(edges.map(edge=>edge.dependency_type))].map(kind=>({id:`dependency:${kind}`,group:"Dependencies",name:dependencyBadge(kind)||"Succeeded",meaning:kind==="HAS_DATA"?"Requires success and written rows":kind==="FAILURE"?"Runs after failure":kind==="ALWAYS"?"Runs after any outcome":"Requires success",sample:<span className="inline-grid gap-1"><svg width="32" height="12"><path d="M 0 6 H 32" style={dependencyStyle(kind)}/></svg><DependencyBadge edge={{dependency_type:kind,consume_repairs:"Y"}}/></span>}));
 if(edges.some(edge=>edge.consume_repairs==="N"))rows.push({id:"no-repairs",group:"Dependencies",name:"No repairs",meaning:"A repaired revision is not consumed",sample:<DependencyBadge edge={{dependency_type:"SUCCESS",consume_repairs:"N"}}/>});
 return rows;
}
export function taskEntries(tasks:CatalogTask[]):LegendEntry[] {
 return tasks.flatMap(task=>{const {icon:Icon,label}=taskSymbol(task);return [{id:`handler:${label}`,group:"Task kinds",name:label,meaning:"Task handler",sample:<Icon className="size-4" style={{color:kindColor(task.script_kind??task.handler)}}/>},{id:`condition:${runCondition(task)}`,group:"Run conditions",name:runCondition(task),meaning:"Required upstream dependency conditions",sample:<RunConditionMark task={task}/>},...(task.active_flag==="N"?[{id:"inactive",group:"Task kinds",name:"Inactive",meaning:"Visible in the definition; not executed",sample:<span className="opacity-40"><DiagramChip>Inactive</DiagramChip></span>}]:[])];});
}
const STAGES:Record<string,[string,string]>={
  source:["Source","An input object read by this task"],
  join:["Join","Combines sources on a condition"],
  filter:["Filter","Keeps the rows that match the WHERE"],
  aggregate:["Aggregate","Groups rows and aggregates values"],
  set:["Set operation","Combines the results of several SELECTs"],
  expression:["Expression","Computes a target column"],
  rules:["Rules","Rejects rows that fail a business rule"],
  write:["Write","The engine action that writes the target"],
  target:["Target","The object this task writes"],
};
export function mappingStageEntry(kind:string,color:string,Icon=Database):LegendEntry {
  const [name,meaning]=STAGES[kind]??[kind.charAt(0).toUpperCase()+kind.slice(1),"A stage of the mapping"];
  return {id:`stage:${kind}`,group:"Stages",name,meaning,sample:<Icon className="size-4" style={{color}}/>};
}
export const highlightedEntry:LegendEntry={id:"highlight",group:"Lineage",name:"Highlighted path",meaning:"Selected item and its connected path",sample:<svg width="36" height="20" viewBox="0 0 36 20" aria-hidden><rect x="1" y="4" width="14" height="12" fill="none" stroke="var(--accent)" strokeWidth="2"/><path d="M 16 10 H 36" stroke="var(--accent)" strokeWidth="2"/></svg>};

const LOGIC_ICON:Record<string,LucideIcon>={filter:Filter,join:GitMerge,aggregate:Sigma,rules:ShieldCheck};
/** A neutral annotation, distinct from the accent outline used for selected lineage. */
export function MappingLogicMark({kind}:{kind:string}) {
 const Icon=LOGIC_ICON[kind]??FunctionSquare;
 return <span className="inline-flex shrink-0 items-center gap-1 text-xs font-normal text-muted"><Icon aria-hidden className="size-3"/>{kindLabels[kind]??"Logic"}</span>;
}
export function mappingLogicEntry(kind:string):LegendEntry {
 return {id:`row-logic:${kind}`,group:"Row logic",name:kindLabels[kind]??"Logic",meaning:`${STAGES[kind]?.[1]??"Extra recorded logic"}; this row marker is not a lineage selection`,sample:<MappingLogicMark kind={kind}/>};
}

export function MappingConditions({conditions}:{conditions:string[]}) {
 return <span title={conditions.join("; ")}>{conditions.length} condition{conditions.length===1?"":"s"} across columns</span>;
}

export function RunConditionMark({task}:{task:CatalogTask}) {
 return <span className="shrink-0 rounded-sm border border-border px-1">{runCondition(task)}</span>;
}
