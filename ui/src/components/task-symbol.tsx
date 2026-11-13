import { Database, Code, Download, Terminal, FileCheck2, Eraser, ShieldCheck, Bell, Hourglass, Network, Table2, Plus, Replace, ListPlus, GitMerge, History, Trash2, ListMinus, Eye, type LucideIcon } from "lucide-react";
import type { CatalogTask } from "@/lib/catalog";
import { handlerLabel } from "@/lib/labels";

/** Task identity stays recognisable independently of its run status. */
export function taskSymbol(task: CatalogTask): { icon: LucideIcon; label: string } {
  if (task.handler === "SQL") {
    const action = task.mapping.write.action;
    const actions:Record<string, {icon:LucideIcon; label:string}> = {
      CREATE_TABLE:{icon:Table2,label:"Create table"}, SETUP_TABLE:{icon:Plus,label:"Set up table"},
      OVERWRITE_TABLE:{icon:Replace,label:"Overwrite"}, APPEND_TABLE:{icon:ListPlus,label:"Append"},
      SCD1_MERGE:{icon:GitMerge,label:"SCD1 merge"}, SCD2_MERGE:{icon:History,label:"SCD2 merge"},
      DROP_TABLE:{icon:Trash2,label:"Drop table"}, DELETE_ROWS:{icon:ListMinus,label:"Delete rows"},
      CREATE_VIEW:{icon:Eye,label:"Create view"},
    };
    return action && actions[action] ? actions[action] : {icon:Database,label:"Managed SQL"};
  }
  if (task.handler === "PYTHON") return task.script_kind === "INGESTION" ? {icon:Download,label:"Python ingestion"} : {icon:Code,label:task.script_kind === "UTILITY" ? "Python utility" : "Python"};
  return {icon:({SQL_SCRIPT:Terminal,FILE_VALIDATION:FileCheck2,ERASURE:Eraser,BUSINESS_RULES:ShieldCheck,EMAIL_ALERT:Bell,EVENT_WAIT:Hourglass,RUN_PIPELINE:Network} as Record<string,LucideIcon>)[task.handler] ?? Code,label:task.handler === "EMAIL_ALERT" ? "Alert" : handlerLabel(task.handler)};
}

export const kindLabels:Record<string,string> = {source:"Source",join:"Join",filter:"Filter",expression:"Expression",aggregate:"Aggregate",rules:"Rules",write:"Write",target:"Target",set:"Set operation"};
/** Three roles, not eight hues: where data comes in, what changes it, and where it lands. */
const ROLE: Record<string, "in" | "mid" | "out"> = {
  source: "in", INGESTION: "in", EVENT_WAIT: "in", FILE_VALIDATION: "in",
  write: "out", target: "out", EMAIL_ALERT: "out", ERASURE: "out", RUN_PIPELINE: "out",
};
export function kindColor(kind: string): string {
  return `var(--kind-${ROLE[kind] ?? "mid"})`;
}
