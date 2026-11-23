import { useState } from "react";
import { Pause, Play } from "lucide-react";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { unavailableAction, useActionAvailability } from "@/hooks";
import type { ActiveRuns, Pipeline } from "@/lib/types";

/** The pipeline pause policy and scheduled resume choice, shared by every entry point. */
export function PipelinePause({code,pipeline}:{code:string;pipeline:Pipeline}) {
  const [then,setThen]=useState("wait");
  const [activeRuns,setActiveRuns]=useState<ActiveRuns>("DRAIN");
  const availability = useActionAvailability(code, pipeline.pipeline_code);
  const policy=<SelectField label="Active runs" value={activeRuns} onChange={value=>setActiveRuns(value as ActiveRuns)}>
    <option value="DRAIN">Stop active runs at the next task</option>
    <option value="FINISH">Let active runs finish</option>
  </SelectField>;
  return <div className="flex flex-wrap gap-2">
    <ActionButton<{message?:string}>
      code={code} label="Pause" title={`Pause ${pipeline.pipeline_code}`}
      effect="Blocks new runs. Running attempts finish. Choose whether admitted runs dispatch more tasks."
      endpoint="/controls" unavailableReason={unavailableAction(availability, "/controls", "POST", { action: "PAUSE" })}
      body={reason=>({pipeline_code:pipeline.pipeline_code,action:"PAUSE",reason,active_runs:activeRuns})}
      describe={result=>result.message??"Pause requested."} onDone={()=>setActiveRuns("DRAIN")}
      icon={<Pause className="size-4" aria-hidden/>} fields={policy}
    />
    <ActionButton<{message?:string}>
      code={code} label="Resume" title={`Resume ${pipeline.pipeline_code}`}
      effect="Allows new runs and releases drained runs under their original admission."
      endpoint="/controls" unavailableReason={unavailableAction(availability, "/controls", "POST", { action: "RESUME" })}
      body={reason=>({pipeline_code:pipeline.pipeline_code,action:"RESUME",reason,...(pipeline.run_schedule?{then}:{})})}
      describe={result=>result.message??"Resume requested."}
      icon={<Play className="size-4" aria-hidden/>}
      fields={pipeline.run_schedule?<SelectField label="After resuming" value={then} onChange={setThen}>
        <option value="wait">Wait for the next scheduled run</option>
        <option value="run-now">Run now</option>
        <option value="catch-up">Catch up missed runs</option>
      </SelectField>:undefined}
    />
    <ActionButton<{message?:string}> code={code} label="Replace pause" title={`Replace pause ${pipeline.pipeline_code}`}
      effect="Atomically changes the open pause mode. No new run is admitted."
      endpoint="/controls" unavailableReason={unavailableAction(availability, "/controls", "POST", { action: "PAUSE", replacement: true })} body={reason=>({pipeline_code:pipeline.pipeline_code,action:"PAUSE",reason,active_runs:activeRuns,replace:true})}
      describe={result=>result.message??"Pause replaced."} onDone={()=>setActiveRuns("DRAIN")} fields={policy} />
  </div>;
}
