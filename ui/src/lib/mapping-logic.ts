import type { CatalogTask } from "@/lib/catalog";

export type LogicRow={expression:string;columns:string[];label:string};
/** Resolve parser aliases to recorded source identities, without parsing SQL in the browser. */
export function mappingFields(task:CatalogTask, columns:string[], tables:readonly {name:string;columns:readonly {name:string}[]}[]=[]):string[] {
  return columns.flatMap(column=>{
    const parts=column.split("."); const name=parts.at(-1)!.replaceAll('"',"").toLowerCase();
    if(parts.length===1){
      const candidates=task.sources.filter(source=>tables.find(table=>table.name===source)?.columns.some(column=>column.name.toLowerCase()===name));
      if(candidates.length===1)return [`${candidates[0]}.${name}`];
      if(candidates.length>1)return [];
      const projected=[...new Set(task.mapping.edges.filter(edge=>edge.source_column===name&&edge.source_object).map(edge=>`${edge.source_object}.${name}`))];
      return projected.length===1?projected:[];
    }
    const alias=parts.slice(0,-1).join(".");
    const source=task.mapping.steps.find(step=>step.kind==="source"&&step.name.toLowerCase()===alias.toLowerCase());
    const object=source?.expression.split(/\s+(?:AS\s+)?/i)[0] ?? alias;
    const resolved=task.sources.find(item=>item.toLowerCase()===object.toLowerCase())
      ?? task.sources.find(item=>object.toLowerCase().endsWith(`.${item.toLowerCase()}`)||item.toLowerCase().endsWith(`.${object.toLowerCase()}`))
      ?? object;
    return [`${resolved}.${name}`];
  });
}
export function stageRows(task:CatalogTask, rows:LogicRow[], name:string,tables:readonly {name:string;columns:readonly {name:string}[]}[]=[]):LogicRow[] {
  return rows.filter(row=>mappingFields(task,row.columns,tables).includes(name)||row.columns.includes(name));
}
export function stageLabel(kind:string):string {return ({join:"Join",filter:"Filter",aggregate:"Aggregate",set:"Set operation"} as Record<string,string>)[kind] ?? kind;}
