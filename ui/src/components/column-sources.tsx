import { SourceAliases } from "@/components/source-aliases";
import { EmptyState } from "@/components/common";
import { DataTable, columnsOf } from "@/components/data-table";
import { AppLink } from "@/components/navigation";
import { stageLabel } from "@/lib/mapping-logic";
import { catalogPath } from "@/lib/routes";
import type { CatalogDoc, CatalogEdge, CatalogTask } from "@/lib/catalog";

const endpoint=(object:string|null,column:string|null)=>object?`${object}${column?`.${column}`:""}`:"No direct source column";

/** Recorded column edges and their task's stage/rule logic have one tabular home. */
export function ColumnSources({code,doc,edges,tasks,target,column}:{code:string;doc:CatalogDoc;edges:CatalogEdge[];tasks:CatalogTask[];target?:string;column?:string}) {
  const byTask=new Map(tasks.map(task=>[task.label,task]));
  const unique=new Map<string,CatalogEdge>();
  for(const edge of [...edges,...tasks.flatMap(task=>task.mapping.edges)]) {
    if((target&&edge.target_object!==target)||(column&&edge.target_column!==column))continue;
    unique.set(JSON.stringify([edge.task,edge.target_object,edge.target_column,edge.source_object,edge.source_column,edge.transformation]),edge);
  }
  for(const task of tasks) {
    if(column||task.lineage.state!=="declared"||!task.target||(target&&task.target!==target)||[...unique.values()].some(edge=>edge.task===task.label))continue;
    for(const source of task.sources) {
      const edge={task:task.label,target_object:task.target,target_column:"(table)",source_object:source,source_column:null,transformation:"declared"};
      unique.set(JSON.stringify(edge),edge);
    }
  }
  const logic=tasks.flatMap(task=>[
    ...task.mapping.steps.flatMap(step=>(step.logic??[]).map(row=>({task:task.label,stage:stageLabel(step.kind),column:row.label==="Output"?row.columns[0]??"":"",expression:row.expression,provenance:"Derived"}))),
    ...doc.rules.filter(rule=>rule.table===task.target&&rule.type==="REJECT").flatMap(rule=>(rule.logic??[{expression:rule.sql,columns:[],label:""}]).map(row=>({task:task.label,stage:`Rules · ${rule.name}`,column:row.columns.join(", "),expression:row.expression,provenance:"Derived"}))),
  ]);
  const unavailable=tasks.filter(task=>task.lineage.state==="unavailable"&&task.lineage.reason);
  const taskLink=(name:string)=><AppLink className="text-accent hover:underline" to={catalogPath(code,"tasks",name)}>{name}</AppLink>;
  return <div className="grid min-w-0 gap-4 [&_.table-cell-content]:line-clamp-none [&_.table-cell-content]:whitespace-pre-wrap">
    {unavailable.map(task=><p role="note" key={task.label} className="m-0 text-sm text-muted">{taskLink(task.label)}: {task.lineage.reason}</p>)}
    {tasks.some(task=>task.lineage.state==="declared")?<p role="note" className="m-0 text-sm text-muted">Declared sources are documented by the developer, not verified against the script. Table-level sources appear under All columns.</p>:null}
    {tasks.map(task=><SourceAliases key={task.label} task={task} label={`SQL source aliases for ${task.label}`}/>)}
    {unique.size?<DataTable find label="Column sources" data={[...unique.values()]} columns={columnsOf<CatalogEdge>([
      {id:"column",header:"Column",value:edge=>endpoint(edge.target_object,edge.target_column),size:300,cell:edge=><span className="font-mono text-xs">{endpoint(edge.target_object,edge.target_column)}</span>},
      {id:"from",header:"Made from",value:edge=>endpoint(edge.source_object,edge.source_column),size:300,cell:edge=><span className="font-mono text-xs">{endpoint(edge.source_object,edge.source_column)}</span>},
      {id:"how",header:"How",value:edge=>edge.transformation,size:240,cell:edge=><span className="text-muted">{edge.transformation}</span>},
      {id:"provenance",header:"Provenance",value:edge=>byTask.get(edge.task)?.lineage.state==="declared"?"Declared":"Derived",size:120},
      {id:"task",header:"Task",value:edge=>edge.task,size:260,cell:edge=>taskLink(edge.task)},
    ])}/>:!unavailable.length?<EmptyState title="No column lineage was traced for this selection." nextStep="Choose All columns for declared table-level sources, or declare task sources and targets, refresh lineage, then rebuild the catalog."/>:null}
    {logic.length?<section className="grid min-w-0 gap-2" aria-label="Task logic">
      <h3 className="m-0 text-sm font-semibold">Task logic</h3>
      <p className="m-0 text-xs text-muted">Stage and rule expressions for the writing tasks. This context is retained independently of the output-column filter above.</p>
      <DataTable label="Task logic" data={logic} columns={columnsOf<typeof logic[number]>([
        {id:"stage",header:"Stage",value:row=>row.stage,size:160},
        {id:"column",header:"Column",value:row=>row.column,size:200},
        {id:"logic",header:"Logic",value:row=>row.expression,size:400},
        {id:"provenance",header:"Provenance",value:row=>row.provenance,size:120},
        {id:"task",header:"Task",value:row=>row.task,cell:row=>taskLink(row.task),size:260},
      ])}/>
    </section>:null}
  </div>;
}
