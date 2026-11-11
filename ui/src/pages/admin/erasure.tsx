import { createColumnHelper } from "@tanstack/react-table";
import * as React from "react";
import { Field, inputClass, Notice } from "@/components/common";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DataTable } from "@/components/data-table";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { failureText, useProjectInfo, useWrite } from "@/hooks";
import { project } from "@/lib/api";
import { ListState, useAdminList } from "./shared";

interface Entry {
  table_name: string;
  column_name: string;
  key_hmac: string;
  active_flag: string;
}

const columns = createColumnHelper<Entry>();
type Mode = "register" | "lift";

/** Personal-data erasure: preview first, then register or lift after the usual confirmation. The identifier value is never displayed. */
export function ErasureTab({ code }: { code: string }) {
  const info = useProjectInfo(code).project;
  const toast = useToast();
  const list = useAdminList<{ entries: Entry[] }>(`${project(code)}/erasure`, undefined, !!code);
  const [table, setTable] = React.useState("");
  const [column, setColumn] = React.useState("");
  const [value, setValue] = React.useState("");
  const [preview, setPreview] = React.useState<unknown>(null);
  const [mode, setMode] = React.useState<Mode | null>(null);
  const body = (reason: string, extra: Record<string, unknown>) => ({ table, column, value, reason, ...extra });
  const previewIt = useWrite<unknown>(`${project(code)}/erasure`, setPreview);
  const apply = useWrite<unknown>(`${project(code)}/erasure`, () => {
    toast(mode === "lift" ? "Erasure entry lifted." : "Erasure registered and applied.");
    setMode(null);
    setValue("");
    setPreview(null);
  });
  const ready = table.trim() !== "" && column.trim() !== "" && value !== "";
  if (!code) return <Notice info>Choose a project to manage its erasure register.</Notice>;
  return (
    <div className="grid gap-5">
      <ListState query={list} what="erasure entries" />
      <Card>
        <CardHeader>
          <CardTitle>Erasure register · {list.data?.entries.length ?? 0}</CardTitle>
        </CardHeader>
        <DataTable
          label="Erasure register"
          data={list.data?.entries ?? []}
          nextStep="Use the erasure form below to record a privacy request."
          empty={list.isSuccess ? "No erasure entries." : undefined}
          columns={[
            columns.accessor("table_name", { header: "Table" }),
            columns.accessor("column_name", { header: "Column" }),
            columns.accessor("key_hmac", { header: "Key HMAC", cell: (c) => <code className="break-all font-mono text-xs">{c.getValue()}</code> }),
            columns.display({ id: "state", header: "State", cell: (c) => (c.row.original.active_flag === "Y" ? "Active" : "Lifted") }),
          ]}
        />
      </Card>
      <Card className="max-w-xl p-5">
        <form className="grid gap-4" onSubmit={(e) => e.preventDefault()}>
          <p className="m-0 text-sm text-muted">Register the first warehouse table where the identifier enters. Preview shows tables, counts and lineage boundaries. External source systems are never changed. The confirmation names the table and column; it never displays the identifier value.</p>
          <Field label="First table (catalog.schema.table)">
            <input className={inputClass} value={table} onChange={(e) => setTable(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Identifier column">
            <input className={inputClass} value={column} onChange={(e) => setColumn(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Identifier value (private)">
            <input className={inputClass} type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" spellCheck={false} />
          </Field>
          {previewIt.isError ? <Notice>{failureText(previewIt.error)}</Notice> : null}
          <div className="flex flex-wrap gap-2">
            <Button disabled={!ready || previewIt.isPending} onClick={() => previewIt.mutate(body("Preview before erasing", { dry_run: true }))}>
              Preview erasure
            </Button>
            <Button variant="danger" disabled={!ready || preview === null} onClick={() => { apply.reset(); setMode("register"); }}>
              Register and erase
            </Button>
            <Button disabled={!ready} onClick={() => { apply.reset(); setMode("lift"); }}>
              Lift entry
            </Button>
          </div>
        </form>
        {preview !== null ? <pre className="m-0 mt-4 overflow-x-auto rounded-md bg-idle-bg p-3 font-mono text-xs">{JSON.stringify(preview, null, 2)}</pre> : null}
      </Card>
      {info ? (
        <ConfirmDialog
          open={mode !== null}
          title={mode === "lift" ? `Lift the erasure of ${column} in ${table}` : `Erase ${column} in ${table}`}
          action={mode === "lift" ? "Lift entry" : "Register and erase"}
          effect={mode === "lift" ? "Stops erasing this identifier when the table is loaded again." : "Registers the identifier and erases it from the table and the tables downstream of it. This cannot be undone."}
          projectCode={code}
          env={{ type: info.environment_type, name: info.environment_name }}
          error={failureText(apply.error)}
          busy={apply.isPending}
          onConfirm={(reason) => apply.mutate(body(reason, mode === "lift" ? { lift: true } : {}))}
          onClose={() => setMode(null)}
        />
      ) : null}
    </div>
  );
}
