import * as React from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { ActionButton } from "@/components/action-button";
import { Field, inputClass, SelectField } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { unavailableAction, useActionAvailability } from "@/hooks";
import type { Binding, RoleView } from "@/lib/types";
import { AUDIENCES, ENVIRONMENTS, BindingRevoke, useRoleNames, what, where, who } from "./access";
import { done, ListState, useAdminList } from "./shared";

const roleColumns = createColumnHelper<RoleView>();
const bindingColumns = createColumnHelper<Binding>();

/** Roles are named sets of commands; built-in CAN_* roles cannot change. */
export function RolesTab() {
  const list = useAdminList<{ roles: RoleView[] }>("/api/v1/roles");
  const roles = list.data?.roles ?? [];
  const [selectedName, setSelectedName] = React.useState<string | null>(null);
  const selected = roles.find((role) => role.name === selectedName);
  const custom = roles.filter((r) => !r.built_in && r.active_flag === "Y").map((r) => r.name);
  const columns = React.useMemo(() => [
            roleColumns.accessor("name", { header: "Role", cell: (c) => <Button variant="ghost" className="h-auto justify-start whitespace-normal break-all p-0 text-left font-medium text-accent hover:underline" aria-label={`Describe role ${c.getValue()}`} onClick={() => setSelectedName(c.getValue())}>{c.getValue()}</Button> }),
            roleColumns.display({ id: "kind", header: "Kind", cell: (c) => (c.row.original.built_in ? "Built-in" : c.row.original.active_flag === "Y" ? "Custom" : "Disabled") }),
            roleColumns.display({ id: "actions", header: "Commands", cell: (c) => <span className="block max-w-2xl whitespace-normal break-words text-xs">{c.row.original.actions.join(", ") || "None yet"}</span> }),
            roleColumns.display({
              id: "act",
              header: "Actions",
              cell: (c) => {
                const r = c.row.original;
                return (
                  <ActionButton<unknown>
                    label="Disable"
                    title={`Disable ${r.name}`}
                    effect="Every binding of this role stops allowing anything on the next request."
                    endpoint="/roles/disable" availabilityTarget={{ role_name: r.name }}
                    askReason={false}
                    body={() => ({ name: r.name })}
                    describe={done("Role disabled.")}
                    variant="danger"
                    size="sm"
                  />
                );
              },
            }),
  ], []);
  return (
    <div className="grid min-w-0 grid-cols-1 gap-5">
      <ListState query={list} what="roles" />
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Roles · {roles.length}</CardTitle>
          <div className="flex flex-wrap gap-2">
            <FormAction
              label="Create role"
              title="Create a role"
              effect="Creates an empty custom role; add the commands it allows next."
              endpoint="/roles"
              askReason={false}
              variant="primary"
              describe={done("Role created.")}
              fields={[
                { name: "name", label: "Role name, such as data-analyst", required: true },
                { name: "description", label: "Description" },
              ]}
            />
            <FormAction
              label="Add command"
              title="Add a command to a role"
              effect="Everyone the role is bound to may run this command where the binding applies."
              endpoint="/roles/actions"
              askReason={false}
              describe={done("Command added.")}
              fields={[
                { name: "name", label: "Role", kind: "select", options: custom, required: true },
                { name: "action", label: "Command, such as run or pool set", required: true },
              ]}
            />
            <FormAction
              label="Remove command"
              title="Remove a command from a role"
              effect="Stops this role allowing the command on the next request."
              endpoint="/roles/actions/remove"
              askReason={false}
              describe={done("Command removed.")}
              fields={[
                { name: "name", label: "Role", kind: "select", options: custom, required: true },
                { name: "action", label: "Command to remove", required: true },
              ]}
            />
          </div>
        </CardHeader>
        <DataTable
          find
          label="Roles"
          data={roles}
          nextStep="Create a role above, add its commands, then grant it on the Access tab or below."
          empty={list.isSuccess ? "No roles." : undefined}
          columns={columns}
        />
      </Card>
      <Dialog open={!!selected} onClose={() => setSelectedName(null)} labelledBy="role-details-title" className="max-h-[85dvh]">
        {selected ? <div className="grid gap-3 p-4">
          <div className="flex items-start justify-between gap-3">
            <h2 id="role-details-title" className="min-w-0 break-all font-semibold">{selected.name}</h2>
            <Button onClick={() => setSelectedName(null)}>Close</Button>
          </div>
          <p className="min-w-0 break-words text-sm text-muted">{selected.description || "No description."}</p>
          <h3 className="text-sm font-medium">Commands · {selected.actions.length}</h3>
          {selected.actions.length ? <ul tabIndex={0} className="grid max-h-[60dvh] gap-1 overflow-auto text-sm focus-visible:outline-2 focus-visible:outline-ring">
            {selected.actions.map((action) => <li key={action} className="break-words"><code>{action}</code></li>)}
          </ul> : <p className="text-sm text-muted">No commands yet.</p>}
        </div> : null}
      </Dialog>
      <WideAccess />
      <AccessExplanation />
    </div>
  );
}

/** Bindings that reach every project, or every project of one environment type. */
function WideAccess() {
  const [reach, setReach] = React.useState("deployment");
  const params = reach === "deployment" ? { deployment: true } : { environment: reach };
  const list = useAdminList<{ bindings: Binding[] }>("/api/v1/access/grants", params);
  const roles = useRoleNames();
  const bindings = (list.data?.bindings ?? []).filter((b) => b.active_flag === "Y");
  const label = reach === "deployment" ? "every project" : `every ${reach} project`;
  const tableColumns = React.useMemo(() => [
          bindingColumns.display({ id: "who", header: "Who", cell: (c) => <span className="font-medium">{who(c.row.original)}</span> }),
          bindingColumns.display({ id: "what", header: "Gets", cell: (c) => what(c.row.original) }),
          bindingColumns.display({ id: "where", header: "Where", cell: (c) => where(c.row.original) }),
          bindingColumns.display({
            id: "act",
            header: "Actions",
            cell: (c) => <BindingRevoke binding={c.row.original} />,
          }),
        ], []);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Access to {label} · {bindings.length}</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <SelectField compact label="Reach" value={reach} onChange={setReach}>
            <option value="deployment">Every project</option>
            {ENVIRONMENTS.map((e) => (
              <option key={e} value={e}>
                Every {e} project
              </option>
            ))}
          </SelectField>
          <FormAction
            label="Grant access"
            title={`Grant access to ${label}`}
            effect={`Give one account, group or audience a role or one command on ${label}.`}
            endpoint="/access/grants"
            variant="primary"
            describe={done("Access granted.")}
            extra={params}
            fields={[
              { name: "account", label: "Account" },
              { name: "group", label: "Group" },
              { name: "audience", label: "Every account with role", kind: "select", options: AUDIENCES, blank: "None" },
              { name: "role", label: "Role", kind: "select", options: roles, blank: "None (give one command)" },
              { name: "action", label: "Or one command, such as pool set" },
            ]}
          />
        </div>
      </CardHeader>
      <ListState query={list} what="access" />
      <DataTable
        label={`Access to ${label}`}
        data={bindings}
        nextStep="Grant a role or one command above."
        empty={list.isSuccess ? "No access here yet." : undefined}
        columns={tableColumns}
      />
    </Card>
  );
}

/** Evaluate the same authorization decision without executing the command. */
function AccessExplanation() {
  const availability = useActionAvailability();
  const reason = unavailableAction(availability, "/access/explain", "GET");
  const [probe, setProbe] = React.useState<Record<string, string>>();
  const result = useAdminList<{ allowed: boolean; allowed_by: string[]; refusal: string | null; roles_with_action: string[] }>("/api/v1/access/explain", probe, !!probe);
  return <Card className="min-w-0">
    <CardHeader><CardTitle>Explain access</CardTitle></CardHeader>
    <form className="grid gap-3 p-4 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      if (reason) return;
      setProbe(Object.fromEntries(Array.from(fields.entries()).filter(([, value]) => String(value).trim()).map(([name, value]) => [name, String(value).trim()])));
    }}>
      <Field label="Account"><input name="account" required autoComplete="off" className={inputClass} /></Field>
      <Field label="Command"><input name="action" required autoComplete="off" className={inputClass} /></Field>
      <Field label="Project (optional)"><input name="project" autoComplete="off" className={inputClass} /></Field>
      <Field label="Pipeline (optional)"><input name="pipeline" autoComplete="off" className={inputClass} /></Field>
      <Button type="submit" unavailableReason={reason}>Explain access</Button>
    </form>
    <ListState query={result} what="access explanation" />
    {result.data ? <div className="grid gap-2 p-4 text-sm" role="status">
      <p>{result.data.allowed ? "Allowed" : "Refused"}</p>
      {result.data.allowed_by.map((source) => <p key={source}>{source}</p>)}
      {result.data.refusal ? <p>{result.data.refusal}</p> : null}
      <p>Roles with this command: {result.data.roles_with_action.join(", ") || "None"}</p>
    </div> : null}
  </Card>;
}
