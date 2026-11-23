import { useState } from "react";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { unavailableAction, useActionAvailability } from "@/hooks";
import type { TaskPause } from "@/lib/types";

/** One standing outcome form for task history, run inspection and the Paused list. */
export function TaskPauseControl({ code, pipeline, task }: { code: string; pipeline: string; task: string }) {
  const availability = useActionAvailability(code, pipeline, true, { task_code: task });
  const [outcome, setOutcome] = useState<TaskPause["outcome"]>("SKIPPED");
  const fields = <SelectField label="Task outcome" value={outcome} onChange={(value) => setOutcome(value as TaskPause["outcome"])}>
    <option value="SKIPPED">SKIPPED</option><option value="SUCCESS">SUCCESS</option><option value="FAILED">FAILED</option>
  </SelectField>;
  return (
    <div className="flex flex-wrap gap-2">
      <ActionButton<{ message?: string }> code={code} label="Pause task" title={`Pause task ${task}`}
        effect="Applies the selected outcome in runs where this task has yet to start. Running tasks finish normally."
        endpoint="/controls" unavailableReason={unavailableAction(availability, "/controls", "POST", { action: "PAUSE" })}
        body={(reason) => ({ pipeline_code: pipeline, task_code: task, action: "PAUSE", reason, outcome })}
        fields={fields} describe={(result) => result.message ?? "Task paused."} onDone={() => setOutcome("SKIPPED")} />
      <ActionButton<{ message?: string }> code={code} label="Resume" title={`Resume task ${task}`}
        effect="Removes the standing task outcome without creating a run."
        endpoint="/controls" unavailableReason={unavailableAction(availability, "/controls", "POST", { action: "RESUME" })}
        body={(reason) => ({ pipeline_code: pipeline, task_code: task, action: "RESUME", reason })}
        describe={(result) => result.message ?? "Task resumed."} />
      <ActionButton<{ message?: string }> code={code} label="Replace task pause" title={`Replace pause for task ${task}`}
        effect="Atomically replaces the standing pause for runs without an admitted pause version."
        endpoint="/controls" unavailableReason={unavailableAction(availability, "/controls", "POST", { action: "PAUSE", replacement: true })}
        body={(reason) => ({ pipeline_code: pipeline, task_code: task, action: "PAUSE", outcome, replace: true, reason })}
        fields={fields} describe={(result) => result.message ?? "Task pause replaced."} onDone={() => setOutcome("SKIPPED")} />
    </div>
  );
}
