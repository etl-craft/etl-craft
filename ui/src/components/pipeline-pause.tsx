import { useState } from "react";
import { Pause, Play } from "lucide-react";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { useCanRun } from "@/hooks";
import type { ActiveRuns, Pipeline } from "@/lib/types";

/** The pipeline pause policy and scheduled resume choice, shared by every entry point. */
export function PipelinePause({code,pipeline}:{code:string;pipeline:Pipeline}) {
  const [then,setThen]=useState("wait");
  const [activeRuns,setActiveRuns]=useState<ActiveRuns>("DRAIN");
  const canRun=useCanRun(code);
  if(!canRun)return null;
  const paused=!!pipeline.paused;
  const verb=paused?"Resume":"Pause";
  const policy=<SelectField label="Active runs" value={activeRuns} onChange={value=>setActiveRuns(value as ActiveRuns)}>
    <option value="DRAIN">Stop active runs at the next task</option>
    <option value="FINISH">Let active runs finish</option>
  </SelectField>;
  return <div className="flex flex-wrap gap-2">
    <ActionButton<{message?:string}>
      code={code} label={verb} title={`${verb} ${pipeline.pipeline_code}`}
      effect={paused?"Allows new runs and releases drained runs under their original admission.":"Blocks new runs. Running attempts finish; choose whether admitted runs dispatch more tasks."}
      endpoint="/controls"
      body={reason=>({pipeline_code:pipeline.pipeline_code,action:paused?"RESUME":"PAUSE",reason,...(paused?(pipeline.run_schedule?{then}:{}):{active_runs:activeRuns})})}
      describe={result=>result.message??`${verb} requested.`} onDone={()=>setActiveRuns("DRAIN")}
      icon={paused?<Play className="size-4" aria-hidden/>:<Pause className="size-4" aria-hidden/>}
      fields={paused?(pipeline.run_schedule?<SelectField label="After resuming" value={then} onChange={setThen}>
        <option value="wait">Wait for the next scheduled run</option>
        <option value="run-now">Run now</option>
        <option value="catch-up">Catch up missed runs</option>
      </SelectField>:undefined):policy}
    />
    {paused?<ActionButton<{message?:string}> code={code} label="Replace pause" title={`Replace pause ${pipeline.pipeline_code}`}
      effect={`Atomically changes the open pause mode from ${pipeline.paused?.active_runs}. No new run is admitted.`}
      endpoint="/controls" body={reason=>({pipeline_code:pipeline.pipeline_code,action:"PAUSE",reason,active_runs:activeRuns,replace:true})}
      describe={result=>result.message??"Pause replaced."} onDone={()=>setActiveRuns("DRAIN")} fields={policy} />:null}
  </div>;
}
