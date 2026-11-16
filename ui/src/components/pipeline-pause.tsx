import { useState } from "react";
import { Pause, Play } from "lucide-react";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { useCanRun } from "@/hooks";
import type { Pipeline } from "@/lib/types";

/** The same pipeline pause/resume confirmation in its header and list row. */
export function PipelinePause({code,pipeline}:{code:string;pipeline:Pipeline}) {
  const [then,setThen]=useState("wait");
  const canRun=useCanRun(code);
  if(!canRun)return null;
  const paused=!!pipeline.paused;
  const verb=paused?"Resume":"Pause";
  return <ActionButton<{message?:string}>
    code={code}
    label={verb}
    title={`${verb} ${pipeline.pipeline_code}`}
    effect={paused?"Allows automatic runs again.":"Stops new automatic runs. Runs already started continue."}
    endpoint="/controls"
    body={reason=>({pipeline_code:pipeline.pipeline_code,action:paused?"RESUME":"PAUSE",reason,...(paused?{then}: {})})}
    describe={result=>result.message??`${verb} requested.`}
    icon={paused?<Play className="size-4" aria-hidden/>:<Pause className="size-4" aria-hidden/>}
    fields={paused&&pipeline.run_schedule?<SelectField label="After resuming" value={then} onChange={setThen}>
      <option value="wait">Wait for the next scheduled run</option>
      <option value="run-now">Run now</option>
      <option value="catch-up">Catch up missed runs</option>
    </SelectField>:undefined}
  />;
}
