import {expect,it} from "vitest";
import {mappingFields,stageRows} from "@/lib/mapping-logic";
import type {CatalogTask} from "@/lib/catalog";
it("places one-column predicates on their row and leaves multi-column conditions intact",()=>{
 const task={sources:["raw.t"],mapping:{steps:[{kind:"source",expression:"raw.t AS o",name:"o"}],edges:[{source_object:"raw.t",source_column:"a"},{source_object:"raw.t",source_column:"b"}]}} as CatalogTask;
 const rows=[{expression:"a > 0",columns:["a"],label:""},{expression:"b = 'x'",columns:["b"],label:""},{expression:"c > 1 OR d < 2",columns:[],label:""},{expression:"a < b",columns:[],label:""}];
 expect(stageRows(task,rows,"raw.t.a").map(row=>row.expression)).toEqual(["a > 0"]);
 expect(stageRows(task,rows,"raw.t.b").map(row=>row.expression)).toEqual(["b = 'x'"]);
 expect(rows.filter(row=>!row.columns.length)).toHaveLength(2);
 expect(mappingFields(task,["o.a"])).toEqual(["raw.t.a"]);
 expect(mappingFields(task,["O.A"])).toEqual(["raw.t.a"]);
 task.mapping.steps[0]!.expression="warehouse.raw.t AS o";
 expect(mappingFields(task,["o.a"])).toEqual(["raw.t.a"]);
});

it("keeps an unprojected predicate field from its declared source schema",()=>{
 const task={sources:["raw.t"],mapping:{steps:[{kind:"source",expression:"raw.t",name:"t"}],edges:[{source_object:"raw.t",source_column:"id"}]}} as CatalogTask;
 expect(mappingFields(task,["amount"],[{name:"raw.t",columns:[{name:"id"},{name:"amount"}]}])).toEqual(["raw.t.amount"]);
});
