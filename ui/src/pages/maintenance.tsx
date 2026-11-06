import * as React from "react";
import { useParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { Field, inputClass, Notice, PageHeader, SelectField } from "@/components/common";
import { Preview } from "@/components/preview";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useProjectInfo, useRoleAtLeast } from "@/hooks";
import { getJson, postJson, project } from "@/lib/api";
import { useDocumentTitle } from "@/title";

const ACTIONS = ["CREATE_TABLE", "SETUP_TABLE", "OVERWRITE_TABLE", "APPEND_TABLE", "SCD1_MERGE", "SCD2_MERGE", "DELETE_ROWS"];
const text = (r: unknown) => (typeof r === "object" && r && "message" in r ? String((r as { message: unknown }).message) : "Done.");

export function Maintenance() {
  const { project: code = "" } = useParams();
  const admin = useRoleAtLeast("admin");
  const info = useProjectInfo(code);
  useDocumentTitle("Maintenance", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const [archive, setArchive] = React.useState("");
  const [target, setTarget] = React.useState("");
  const [action, setAction] = React.useState("");
  const [upgradeTarget, setUpgradeTarget] = React.useState("");
  if (!admin) return <Notice>The maintenance page needs the admin role; ask an administrator.</Notice>;
  const purge = { archive_to: archive.trim() || undefined };
  const upgrade = { action: action || undefined, target: upgradeTarget.trim() || undefined };
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Maintenance" subtitle={`${code} · each task shows what it would do first; every request is recorded with your account`} />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Purge history</CardTitle>
          </CardHeader>
          <div className="grid gap-3 p-4">
            <p className="m-0 text-sm text-muted">Removes audit history and log files older than the retention settings in craft-connector.yml. Runs that are still active are never removed.</p>
            <Field label="Archive to (optional)">
              <input className={inputClass} placeholder="file:///backups/etl-craft or s3://bucket/prefix" value={archive} onChange={(e) => setArchive(e.target.value)} />
            </Field>
            <Preview label="Preview purge" run={() => postJson(`${project(code)}/purge`, { ...purge, dry_run: true })} />
            <ActionButton<unknown> code={code} label="Purge" title="Purge history" effect="Removes the history the preview listed. This cannot be undone unless you gave an archive location." endpoint="/purge" body={(reason) => ({ ...purge, dry_run: false, reason })} describe={() => "History purged."} variant="danger" />
          </div>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Rehash a merge target</CardTitle>
          </CardHeader>
          <div className="grid gap-3 p-4">
            <p className="m-0 text-sm text-muted">Recomputes the version 2 row hashes of an existing SCD1 or SCD2 target so its merges can run.</p>
            <Field label="Target table">
              <input className={inputClass} placeholder="schema.table" value={target} onChange={(e) => setTarget(e.target.value)} />
            </Field>
            <Preview label="Preview SQL" disabled={!target.trim()} run={() => getJson(`${project(code)}/rehash`, { target: target.trim() })} />
            <ActionButton<unknown> code={code} label="Rehash" title={`Rehash ${target}`} effect="Merges into this target wait until the rehash commits." endpoint="/rehash" body={(reason) => ({ target: target.trim(), reason })} describe={() => "Target rehashed."} variant="danger" />
          </div>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Upgrade target audit columns</CardTitle>
          </CardHeader>
          <div className="grid gap-3 p-4">
            <p className="m-0 text-sm text-muted">Adds the audit columns the current version writes to existing targets. Leave both fields empty for every configured target.</p>
            <SelectField label="SQL action" value={action} onChange={setAction}>
              <option value="">Every action</option>
              {ACTIONS.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </SelectField>
            <Field label="Target table (optional)">
              <input className={inputClass} placeholder="schema.table" value={upgradeTarget} onChange={(e) => setUpgradeTarget(e.target.value)} />
            </Field>
            <Preview label="Preview SQL" run={() => postJson(`${project(code)}/targets/upgrade`, { ...upgrade, dry_run: true })} />
            <ActionButton<unknown> code={code} label="Upgrade" title="Upgrade audit columns" effect="Adds the previewed audit columns to these targets." endpoint="/targets/upgrade" body={(reason) => ({ ...upgrade, dry_run: false, reason })} describe={() => "Audit columns upgraded."} variant="danger" />
          </div>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Clone Engine DB tables</CardTitle>
          </CardHeader>
          <div className="grid gap-3 p-4">
            <p className="m-0 text-sm text-muted">Copies the Engine DB tables chosen by Cloning.Scope into the warehouse, replacing the previous copies. Business tables are not touched. Cloning must be enabled in craft-connector.yml; the answer says so when it is not.</p>
            <ActionButton<unknown> code={code} label="Clone now" title="Clone Engine DB tables" effect="Copies the Engine DB tables into the warehouse now, replacing the previous copies." endpoint="/clones" body={(reason) => ({ reason })} describe={text} />
          </div>
        </Card>
      </div>
    </div>
  );
}
