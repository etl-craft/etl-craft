import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { unavailableAction, useActionAvailability } from "@/hooks";
import { getJson, project } from "@/lib/api";
import type { Capabilities, ControlView } from "@/lib/types";

export const EFFECT: Record<string, string> = {
  STOP: "Asks running attempts to stop. Acknowledged when execution ends.",
  ABORT: "Ends the work in this scope without further attempts.",
  RECOVER: "Reopens the scope: failed and unfinished work runs again.",
  RESTART: "Replaces the scope's work in a new execution context.",
  RUN_PAUSED: "Gives this one run permission while its pipeline remains paused.",
};
export const DANGER = new Set(["STOP", "ABORT"]);
export const label = (action: string) => action.charAt(0) + action.slice(1).toLowerCase().replace("_", " ");

/**
 * The run or task controls the server says are possible now, each behind the one confirmation;
 * the ones that are not possible say why, instead of disappearing.
 */
export function ScopeControls({ code, pipeline, runId, task, elsewhere = [] }: { code: string; pipeline: string; runId: number; task?: string; elsewhere?: string[] }) {
  const availability = useActionAvailability(code, pipeline, !!task, { task_code: task, run_id: runId });
  const [status, setStatus] = React.useState("SUCCESS");
  const caps = useQuery({
    queryKey: ["capabilities", code, pipeline, runId, task ?? ""],
    queryFn: () => getJson<Capabilities>(`${project(code)}/capabilities`, { pipeline_code: pipeline, run_id: runId, task_code: task }),
  });
  if (!caps.data) return null;
  const scope = task ? `task ${task} in run ${runId}` : `run ${runId}`;
  const actions = caps.data.actions.filter((a) => !elsewhere.includes(a.action));
  return (
    <div className="grid gap-2" aria-label={`Controls for ${scope}`}>
      <div className="flex flex-wrap items-start gap-2">
        {actions.map((a) => (
            <ActionButton<ControlView>
              key={a.action}
              code={code}
              label={label(a.action)}
              unavailableReason={a.available ? undefined : a.reason}
              title={`${label(a.action)} ${scope}`}
              effect={`${EFFECT[a.action] ?? ""} ${a.preserves_successful_work ? "Work that already succeeded is kept." : "Work that already succeeded may be replaced."}`.trim()}
              endpoint="/controls"
              body={(reason) => ({ pipeline_code: pipeline, run_id: runId, action: a.action, reason, ...(task ? { task_code: task } : {}) })}
              describe={(r) => `${label(a.action)} requested: control #${r.control_id}. ${r.message}`}
              variant={DANGER.has(a.action) ? "danger" : "outline"}
              size="sm"
            />
          ))}
        {task ? (
          <ActionButton<{ message?: string }>
            code={code}
            label="Mark as"
            title={`Mark ${scope}`}
            effect="Records the chosen status for this task run, as an operator decision."
            endpoint="/marks"
            unavailableReason={unavailableAction(availability, "/marks")}
            body={(reason) => ({ pipeline_code: pipeline, run_id: runId, task_code: task, status, reason })}
            describe={(r) => r.message ?? "Mark recorded."}
            fields={
              <SelectField label="Mark as" value={status} onChange={setStatus}>
                {["SUCCESS", "FAILED", "SKIPPED"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </SelectField>
            }
            size="sm"
          />
        ) : null}
      </div>
    </div>
  );
}

