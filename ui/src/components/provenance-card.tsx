import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { Field, inputClass, Loading, Notice, SelectField } from "@/components/common";
import { RecordTable } from "@/components/record-table";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useIdentity } from "@/hooks";
import { failureText } from "@/hooks";
import { postJson, project } from "@/lib/api";
import type { ValueResult } from "@/lib/types";

/** Who last wrote each value of one business key in a merge task's target, and which values are locked. */
export function ProvenanceCard({ code, pipeline, task, keys, columns }: { code: string; pipeline: string; task: string; keys: string[]; columns: string[] }) {
  const admin = useIdentity(code).data?.role === "admin";
  const [key, setKey] = React.useState<Record<string, string>>({});
  const [column, setColumn] = React.useState(columns[0] ?? "");
  const [value, setValue] = React.useState("");
  const [lockRow, setLockRow] = React.useState(false);
  const [unlock, setUnlock] = React.useState("");
  const base = `${project(code)}/values`;
  const scope = { pipeline_code: pipeline, task_code: task, key };
  const look = useMutation({ mutationFn: () => postJson<ValueResult>(base + "/provenance", scope) });
  const complete = keys.every((k) => (key[k] ?? "") !== "");
  const result = look.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Data</CardTitle>
        <span className="text-xs text-muted">Lookups, edits and unlocks are recorded</span>
      </CardHeader>
      <div className="grid gap-4 p-4">
        <p className="m-0 text-[13px] text-muted">Look up one business key in this task&apos;s target to see who last wrote each value and which values are locked against the next merge.</p>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (complete) look.mutate();
          }}
        >
          {keys.map((k) => (
            <Field key={k} label={k}>
              <input value={key[k] ?? ""} onChange={(event) => setKey({ ...key, [k]: event.target.value })} required autoComplete="off" className={inputClass} />
            </Field>
          ))}
          <Button type="submit" variant="primary" disabled={!complete || look.isPending}>
            Look up
          </Button>
        </form>
        {look.isPending ? <Loading what="the key" /> : null}
        {look.isError ? <Notice>{failureText(look.error)}</Notice> : null}
        {result && !result.enabled ? <p className="m-0 text-muted">Value protection is not enabled for {result.target}, so no writer is recorded.</p> : null}
        {result?.enabled ? (
          <div className="grid gap-3">
            <p className="m-0 text-[13px] text-muted">{result.target}</p>
            {result.records.length ? <RecordTable label="Current values" records={result.records} hide={["key_hash"]} /> : <p className="m-0 text-muted">No value of this key is recorded.</p>}
            {result.history.length ? (
              <details>
                <summary className="cursor-pointer text-sm font-medium">History ({result.history.length})</summary>
                <RecordTable label="Value history" records={result.history} hide={["key_hash"]} />
              </details>
            ) : null}
          </div>
        ) : null}
        {admin && complete ? (
          <div className="flex flex-wrap items-start gap-2">
            <ActionButton<{ message?: string }>
              code={code}
              label="Edit a value"
              title={`Edit a value of ${task}`}
              effect="Writes the explicit value for this key; other values are retained. Recorded with your reason."
              endpoint="/values"
              body={(reason) => ({ ...scope, values: { [column]: value }, reason, row_lock: lockRow })}
              describe={() => "The value was saved."}
              size="sm"
              fields={
                <>
                  <SelectField label="Column" value={column} onChange={setColumn}>
                    {columns.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </SelectField>
                  <Field label="New value">
                    <input value={value} onChange={(event) => setValue(event.target.value)} autoComplete="off" className={inputClass} />
                  </Field>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={lockRow} onChange={(event) => setLockRow(event.target.checked)} /> Lock the whole row against the next merge
                  </label>
                </>
              }
            />
            <ActionButton<{ message?: string }>
              code={code}
              label="Unlock values"
              title={`Unlock values of ${task}`}
              effect="Releases locks on this key; with no columns named, every active lock on it."
              endpoint="/values/unlock"
              body={(reason) => ({ ...scope, reason, columns: unlock.split(",").map((c) => c.trim()).filter(Boolean) })}
              describe={() => "The values were unlocked."}
              size="sm"
              fields={
                <Field label="Columns (comma-separated; empty unlocks all)">
                  <input value={unlock} onChange={(event) => setUnlock(event.target.value)} autoComplete="off" className={inputClass} />
                </Field>
              }
            />
          </div>
        ) : null}
      </div>
    </Card>
  );
}
