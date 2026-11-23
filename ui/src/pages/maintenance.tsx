import * as React from "react";
import { useParams } from "react-router-dom";
import { ActionButton } from "@/components/action-button";
import { Field, inputClass, PageHeader } from "@/components/common";
import { Preview } from "@/components/preview";
import { Card, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { unavailableAction, useActionAvailability, useProjectInfo } from "@/hooks";
import { getJson, postJson, project } from "@/lib/api";
import { useDocumentTitle } from "@/title";

const text = (r: unknown) => (typeof r === "object" && r && "message" in r ? String((r as { message: unknown }).message) : "Done.");

export function Maintenance() {
  const { project: code = "" } = useParams();
  const info = useProjectInfo(code);
  useDocumentTitle("Maintenance", code, info.project && { type: info.project.environment_type, name: info.project.environment_name });
  const [archive, setArchive] = React.useState("");
  const [target, setTarget] = React.useState("");
  const availability = useActionAvailability(code, undefined, true, { rehash_target: target.trim() || undefined });
  const purgeReason = unavailableAction(availability, "/purge");
  const rehashTarget = target.trim() ? undefined : "Enter the merge target to rehash.";
  const purge = { archive_to: archive.trim() || undefined };
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Maintenance" subtitle="Each task shows what it would do first; every request is recorded with your account." />
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
            <Preview label="Preview purge" unavailableReason={purgeReason} run={() => postJson(`${project(code)}/purge`, { ...purge, dry_run: true })} />
          </div>
          <CardFooter>
            <ActionButton<unknown> code={code} label="Purge" title="Purge history" effect="Removes the history the preview listed. This cannot be undone unless you gave an archive location." endpoint="/purge" unavailableReason={purgeReason} askReason={false} body={() => ({ ...purge, dry_run: false })} describe={() => "History purged."} variant="danger" />
          </CardFooter>
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
            <Preview label="Preview SQL" unavailableReason={unavailableAction(availability, "/rehash", "GET") ?? rehashTarget} run={() => getJson(`${project(code)}/rehash`, { target: target.trim() })} />
          </div>
          <CardFooter>
            <ActionButton<unknown> code={code} label="Rehash" title={`Rehash ${target}`} effect="Merges into this target wait until the rehash commits." endpoint="/rehash" unavailableReason={unavailableAction(availability, "/rehash") ?? rehashTarget} askReason={false} body={() => ({ target: target.trim() })} describe={() => "Target rehashed."} variant="danger" />
          </CardFooter>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Clone Engine DB tables</CardTitle>
          </CardHeader>
          <div className="grid gap-3 p-4">
            <p className="m-0 text-sm text-muted">Copies the Engine DB tables chosen by Cloning.Scope into the warehouse, replacing the previous copies. Business tables are not touched. Cloning must be enabled in craft-connector.yml; the answer says so when it is not.</p>
          </div>
          <CardFooter>
            <ActionButton<unknown> code={code} label="Clone now" title="Clone Engine DB tables" effect="Copies the Engine DB tables into the warehouse now, replacing the previous copies." endpoint="/clones" unavailableReason={unavailableAction(availability, "/clones")} askReason={false} body={() => ({})} describe={text} />
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
