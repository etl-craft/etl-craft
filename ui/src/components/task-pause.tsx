import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { useCanRun } from "@/hooks";
import { getJson, project } from "@/lib/api";
import type { Pipeline, TaskPause } from "@/lib/types";

/** One standing outcome form for task history, run inspection and the Paused list. */
export function TaskPauseControl({code,pipeline,task}:{code:string;pipeline:string;task:string}) {
  const canRun=useCanRun(code);
  const [outcome,setOutcome]=useState<TaskPause["outcome"]>("SKIPPED");
  const pipe=useQuery({queryKey:["pipeline",code,pipeline],queryFn:()=>getJson<Pipeline>(`${project(code)}/pipelines/${encodeURIComponent(pipeline)}`),enabled:canRun});
  if(!canRun||!pipe.data)return null;
  const paused=pipe.data.task_pauses.some(p=>p.task_code===task);
  const fields=<SelectField label="Task outcome" value={outcome} onChange={value=>setOutcome(value as TaskPause["outcome"])}>
    <option value="SKIPPED">SKIPPED</option><option value="SUCCESS">SUCCESS</option><option value="FAILED">FAILED</option>
  </SelectField>;
  return <div className="flex flex-wrap gap-2">
    <ActionButton<{message?:string}> code={code} label={paused?"Resume":"Pause task"} title={`${paused?"Resume":"Pause"} task ${task}`}
      effect={paused?"Removes the standing task outcome. Does not create a run.":"Applies the selected outcome in runs where this task has not started. Running tasks finish normally; admitted pause versions are retained."}
      endpoint="/controls" body={reason=>({pipeline_code:pipeline,task_code:task,action:paused?"RESUME":"PAUSE",reason,...(paused?{}:{outcome})})}
      fields={paused?undefined:fields} describe={result=>result.message??"Task pause updated."} onDone={()=>setOutcome("SKIPPED")} />
    {paused?<ActionButton<{message?:string}> code={code} label="Replace task pause" title={`Replace pause task ${task}`} effect="Atomically replaces the pause for runs without an admitted pause version. Earlier admissions keep their version."
      endpoint="/controls" body={reason=>({pipeline_code:pipeline,task_code:task,action:"PAUSE",outcome,replace:true,reason})} fields={fields} describe={result=>result.message??"Task pause replaced."} onDone={()=>setOutcome("SKIPPED")} />:null}
  </div>;
}
