import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useId } from "react";
import { Fact, FactList, Loading, Notice } from "@/components/common";
import { AppLink } from "@/components/navigation";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { getJson, project } from "@/lib/api";
import { handlerLabel } from "@/lib/labels";
import { taskPath } from "@/lib/routes";
import type { Graph, TaskDefinition } from "@/lib/types";

/** Task definitions remain inspectable from a grid row, even before its first run. */
export function GridTaskDetails({code,pipeline,task,graph,onClose}:{code:string;pipeline:string;task:string|null;graph:Graph;onClose:()=>void}) {
  const title=useId();
  const definition=useQuery({queryKey:["task",code,pipeline,task],queryFn:()=>getJson<TaskDefinition>(`${project(code)}/task`,{pipeline_code:pipeline,task_code:task??undefined}),enabled:task!==null,staleTime:60_000});
  return <Dialog open={task!==null} onClose={onClose} labelledBy={title}>
    <div className="flex items-center justify-between gap-3 border-b border-border p-4">
      <h2 id={title} className="m-0 min-w-0 break-words text-base font-semibold">Task definition · {task}</h2>
      <Button size="icon" variant="ghost" aria-label="Close task definition" onClick={onClose}><X aria-hidden className="size-4"/></Button>
    </div>
    <div className="grid max-h-[70dvh] gap-4 overflow-auto p-4">
      {definition.isPending?<Loading what="task definition"/>:definition.isError?<Notice>{definition.error.message}</Notice>:<FactList className="sm:grid-cols-2 lg:grid-cols-2">
        <Fact label="Handler">{handlerLabel(definition.data.handler)}</Fact>
        <Fact label="Waits for" valueClassName="min-w-0 break-words">{graph.depends_on[task??""]?.length?graph.depends_on[task??""]!.map(([upstream])=><AppLink key={upstream} className="mr-2 text-accent hover:underline" to={taskPath(code,pipeline,upstream)}>{upstream}</AppLink>):"No upstream tasks"}</Fact>
      </FactList>}
      <AppLink className="text-sm text-accent hover:underline" to={taskPath(code,pipeline,task??"")}>Task history, definition and parameters</AppLink>
    </div>
  </Dialog>;
}
