import { Ban, Database, CircleDashed, Sparkles, X } from "lucide-react";
import type {LegendEntry} from "@/components/legend";
import {dependencyStyle,dependencyBadge,runCondition} from "@/lib/catalog-flow";
import {taskSymbol,kindColor} from "@/components/task-symbol";
import type {CatalogTask} from "@/lib/catalog";

export function dependencyEntries(edges:{dependency_type:string;consume_repairs?:string}[]):LegendEntry[] {
 const rows=[...new Set(edges.map(edge=>edge.dependency_type))].map(kind=>({id:`dependency:${kind}`,group:"Dependencies",name:dependencyBadge(kind)||"Succeeded",meaning:kind==="HAS_DATA"?"Requires success and written rows":kind==="FAILURE"?"Runs after failure":kind==="ALWAYS"?"Runs after any outcome":"Requires success",sample:<span className="flex items-center"><svg width="32" height="12"><path d="M 0 6 H 32" style={dependencyStyle(kind)}/></svg>{kind==="HAS_DATA"?<Database aria-hidden className="ml-1 size-3"/>:kind==="FAILURE"?<X aria-hidden className="ml-1 size-3"/>:null}</span>}));
 if(edges.some(edge=>edge.consume_repairs==="N"))rows.push({id:"no-repairs",group:"Dependencies",name:"No repairs",meaning:"A repaired revision is not consumed",sample:<Ban aria-hidden className="size-3"/>});
 return rows;
}
export function taskEntries(tasks:CatalogTask[]):LegendEntry[] {
 return tasks.flatMap(task=>{const {icon:Icon,label}=taskSymbol(task);return [{id:`handler:${label}`,group:"Task kinds",name:label,meaning:"Task handler",sample:<Icon className="size-4" style={{color:kindColor(task.script_kind??task.handler)}}/>},{id:`condition:${runCondition(task)}`,group:"Run conditions",name:runCondition(task),meaning:"Required upstream successes",sample:<span className="rounded-sm border px-1">{runCondition(task)}</span>},...(task.active_flag==="N"?[{id:"inactive",group:"Task kinds",name:"Inactive",meaning:"Visible in the definition; not executed",sample:<CircleDashed className="size-4 opacity-40"/>}]:[])];});
}
const STAGES:Record<string,[string,string]>={
  source:["Source","A table the SELECT reads"],
  join:["Join","Combines sources on a condition"],
  filter:["Filter","Keeps the rows that match the WHERE"],
  aggregate:["Aggregate","Groups rows and aggregates values"],
  set:["Set operation","Combines the results of several SELECTs"],
  expression:["Expression","Computes a target column"],
  rules:["Rules","Rejects rows that fail a business rule"],
  write:["Write","The engine action that writes the target"],
  target:["Target","The table the task writes"],
};
export function mappingStageEntry(kind:string,color:string,Icon=Database):LegendEntry {
  const [name,meaning]=STAGES[kind]??[kind.charAt(0).toUpperCase()+kind.slice(1),"A stage of the mapping"];
  return {id:`stage:${kind}`,group:"Stages",name,meaning,sample:<Icon className="size-4" style={{color}}/>};
}
export const highlightedEntry:LegendEntry={id:"highlight",group:"Lineage",name:"Highlighted path",meaning:"Selected column and its complete journey",sample:<Sparkles className="size-4 text-accent"/>};
