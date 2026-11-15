import type { CatalogTask } from "@/lib/catalog";

export type LogicRow={expression:string;columns:string[];label:string};
/** The recorded source steps explain SQL aliases without changing the SQL text. */
export function sourceAliases(task:CatalogTask):{alias:string;object:string;query?:string}[] {
  const bindings=task.mapping.steps.filter(step=>step.kind==="source").map(step=>{
    const derived=/^\s*(?:\(|SELECT\b|WITH\b)/i.test(step.expression);
    const object=derived ? step.name : step.expression.split(/\s+(?:AS\s+)?/i)[0]!;
    const resolved=derived ? object : task.sources.find(item=>item.toLowerCase()===object.toLowerCase())
      ?? task.sources.find(item=>object.toLowerCase().endsWith(`.${item.toLowerCase()}`)||item.toLowerCase().endsWith(`.${object.toLowerCase()}`))
      ?? object;
    return {alias:step.name,object:resolved,query:derived ? step.expression : undefined,reference:!derived && object.toLowerCase()===step.name.toLowerCase()};
  });
  const queries=new Set(bindings.filter(binding=>binding.query).map(binding=>binding.alias.toLowerCase()));
  const explained=bindings.filter(binding=>!binding.reference || !queries.has(binding.alias.toLowerCase())).map(({alias,object,query})=>({alias,object,query}));
  return [...new Map(explained.map(binding=>[JSON.stringify(binding),binding] as const)).values()];
}
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
    const resolved=sourceAliases(task).find(({alias:name})=>name.toLowerCase()===alias.toLowerCase())?.object ?? alias;
    return [`${resolved}.${name}`];
  });
}
export function stageRows(task:CatalogTask, rows:LogicRow[], name:string,tables:readonly {name:string;columns:readonly {name:string}[]}[]=[]):LogicRow[] {
  return rows.filter(row=>mappingFields(task,row.columns,tables).includes(name)||row.columns.includes(name));
}
export function stageLabel(kind:string):string {return ({join:"Join",filter:"Filter",aggregate:"Aggregate",set:"Set operation"} as Record<string,string>)[kind] ?? kind;}
