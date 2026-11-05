import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { Fact, FactList, Field, inputClass, SelectField } from "@/components/common";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useCanRun, useTimezone } from "@/hooks";
import { formatTime } from "@/lib/format";
import type { TaskOffset } from "@/lib/types";

/** What a task keeps between runs (an offset or a watermark), and how an operator resets it. */
export function OffsetCard({ code, pipeline, task, offset, runs }: { code: string; pipeline: string; task: string; offset: TaskOffset; runs: number[] }) {
  const tz = useTimezone();
  const canRun = useCanRun(code);
  const [value, setValue] = React.useState(offset.offset_value ?? "");
  const [chosen, setChosen] = React.useState("");
  const run = chosen || String(runs[0] ?? "");
  if (!offset.kind) return null;
  const kind = offset.kind === "OFFSET" ? "offset" : "watermark";
  return (
    <Card>
      <CardHeader>
        <CardTitle>{kind.charAt(0).toUpperCase() + kind.slice(1)}</CardTitle>
        {canRun && runs.length ? (
          <ActionButton<{ message?: string }>
            code={code}
            label={`Reset the ${kind}`}
            title={`Reset the ${kind} of ${task}`}
            effect={`The next run of ${task} starts from the new value. Runs that already finished keep their data. Same as etl-craft mark --${kind}.`}
            endpoint="/marks"
            body={(reason) => ({ pipeline_code: pipeline, task_code: task, run_id: Number(run), [kind]: value, reason })}
            describe={(r) => r.message ?? `The ${kind} was reset.`}
            variant="danger"
            size="sm"
            fields={
              <>
                <Field label="New value">
                  <input value={value} onChange={(event) => setValue(event.target.value)} required autoComplete="off" className={inputClass} />
                </Field>
                <SelectField label="Record the reset against run" value={run} onChange={setChosen}>
                  {runs.map((id) => (
                    <option key={id} value={id}>
                      #{id}
                    </option>
                  ))}
                </SelectField>
              </>
            }
          />
        ) : null}
        {canRun && runs.length === 0 ? <span className="text-xs text-muted">A reset is recorded against a run; it is available once the task has run.</span> : null}
      </CardHeader>
      <div className="p-4">
        {offset.offset_type ? (
          <FactList className="lg:grid-cols-3">
            <Fact label="Stored">
              <span className="break-all font-mono text-xs">{offset.offset_value ?? "None"}</span> <span className="text-muted">{offset.offset_type}</span>
            </Fact>
            {offset.pending_task_run_id ? <Fact label="Pending window">Up to {formatTime(offset.pending_upper_bound, tz)}, held by task run {offset.pending_task_run_id}</Fact> : null}
          </FactList>
        ) : (
          <p className="m-0 text-muted">Nothing stored yet; the first run starts it.</p>
        )}
      </div>
    </Card>
  );
}
