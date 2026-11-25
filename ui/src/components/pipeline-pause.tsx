import { useState } from "react";
import { ChevronDown, Pause, Play } from "lucide-react";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { unavailableAction, useActionAvailability } from "@/hooks";
import type { ActiveRuns, Pipeline } from "@/lib/types";

type Choice = "PAUSE" | "RESUME" | "REPLACE";

/**
 * The pipeline's pause controls as one menu, shared by every entry point. Each item is grayed out
 * with the server's reason when unavailable. The confirmations live outside the menu, which closes
 * when an item is chosen.
 */
export function PipelinePause({ code, pipeline, batchCodes }: { code: string; pipeline: Pipeline; batchCodes?: string[] }) {
  const [then, setThen] = useState("wait");
  const [activeRuns, setActiveRuns] = useState<ActiveRuns>("DRAIN");
  const [open, setOpen] = useState<Choice | null>(null);
  const availability = useActionAvailability(
    code, batchCodes ? undefined : pipeline.pipeline_code, !batchCodes,
    batchCodes ? { pipeline_codes: batchCodes } : undefined,
  );
  const data = batchCodes
    ? { actions: availability.data?.pipelines?.[pipeline.pipeline_code] ?? [] }
    : availability.data;
  const reason = (action: string, replacement = false) =>
    unavailableAction({ ...availability, data }, "/controls", "POST", { action, replacement });
  const policy = (
    <SelectField label="Active runs" value={activeRuns} onChange={(value) => setActiveRuns(value as ActiveRuns)}>
      <option value="DRAIN">Stop active runs at the next task</option>
      <option value="FINISH">Let active runs finish</option>
    </SelectField>
  );
  const confirm = (choice: Choice) => (value: boolean) => setOpen(value ? choice : null);
  return (
    <div className="relative inline-flex">
      <DropdownMenu>
        <DropdownTrigger asChild>
          <Button size="sm" variant="outline" aria-label={`Pause options for ${pipeline.pipeline_code}`}>
            Pause
            <ChevronDown className="size-3.5" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent align="end">
          <DropdownItem unavailableReason={reason("PAUSE")} onSelect={() => setOpen("PAUSE")}>
            <Pause className="size-4" aria-hidden /> Pause
          </DropdownItem>
          <DropdownItem unavailableReason={reason("RESUME")} onSelect={() => setOpen("RESUME")}>
            <Play className="size-4" aria-hidden /> Resume
          </DropdownItem>
          <DropdownItem unavailableReason={reason("PAUSE", true)} onSelect={() => setOpen("REPLACE")}>
            Replace pause
          </DropdownItem>
        </DropdownContent>
      </DropdownMenu>
      {/* Absolutely placed: the confirmations take no space in the row, and stay visible. */}
      <div className="absolute left-0 top-full">
        <ActionButton<{ message?: string }>
          code={code} label="Pause" title={`Pause ${pipeline.pipeline_code}`}
          effect="Blocks new runs. Running attempts finish. Choose whether admitted runs dispatch more tasks."
          endpoint="/controls"
          body={(reason) => ({ pipeline_code: pipeline.pipeline_code, action: "PAUSE", reason, active_runs: activeRuns })}
          describe={(result) => result.message ?? "Pause requested."} onDone={() => setActiveRuns("DRAIN")}
          fields={policy} menu={{ open: open === "PAUSE", setOpen: confirm("PAUSE") }}
        />
        <ActionButton<{ message?: string }>
          code={code} label="Resume" title={`Resume ${pipeline.pipeline_code}`}
          effect="Allows new runs and releases drained runs under their original admission."
          endpoint="/controls"
          body={(reason) => ({ pipeline_code: pipeline.pipeline_code, action: "RESUME", reason, ...(pipeline.run_schedule ? { then } : {}) })}
          describe={(result) => result.message ?? "Resume requested."}
          fields={pipeline.run_schedule ? (
            <SelectField label="After resuming" value={then} onChange={setThen}>
              <option value="wait">Wait for the next scheduled run</option>
              <option value="run-now">Run now</option>
              <option value="catch-up">Catch up missed runs</option>
            </SelectField>
          ) : undefined}
          menu={{ open: open === "RESUME", setOpen: confirm("RESUME") }}
        />
        <ActionButton<{ message?: string }>
          code={code} label="Replace pause" title={`Replace pause ${pipeline.pipeline_code}`}
          effect="Atomically changes the open pause mode. No new run is admitted."
          endpoint="/controls"
          body={(reason) => ({ pipeline_code: pipeline.pipeline_code, action: "PAUSE", reason, active_runs: activeRuns, replace: true })}
          describe={(result) => result.message ?? "Pause replaced."} onDone={() => setActiveRuns("DRAIN")}
          fields={policy} menu={{ open: open === "REPLACE", setOpen: confirm("REPLACE") }}
        />
      </div>
    </div>
  );
}
