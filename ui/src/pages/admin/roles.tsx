import * as React from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { ActionButton } from "@/components/action-button";
import { SelectField } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import type { Binding, RoleView } from "@/lib/types";
import { AUDIENCES, ENVIRONMENTS, revokeBody, useRoleNames, what, where, who } from "./access";
import { done, ListState, useAdminList } from "./shared";

const roleColumns = createColumnHelper<RoleView>();
const bindingColumns = createColumnHelper<Binding>();

/** Roles are named sets of commands; built-in CAN_* roles cannot change. */
export function RolesTab() {
  const list = useAdminList<{ roles: RoleView[] }>("/api/v1/roles");
  const roles = list.data?.roles ?? [];
  const custom = roles.filter((r) => !r.built_in && r.active_flag === "Y").map((r) => r.name);
  return (
    <div className="grid gap-5">
      <ListState query={list} what="roles" />
      <Card>
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
          </div>
        </CardHeader>
        <DataTable
          find
          label="Roles"
          data={roles}
          nextStep="Create a role above, add its commands, then grant it on the Access tab or below."
          empty={list.isSuccess ? "No roles." : undefined}
          columns={[
            roleColumns.accessor("name", { header: "Role", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            roleColumns.display({ id: "kind", header: "Kind", cell: (c) => (c.row.original.built_in ? "Built-in" : c.row.original.active_flag === "Y" ? "Custom" : "Disabled") }),
            roleColumns.display({ id: "actions", header: "Commands", cell: (c) => <span className="text-xs">{c.row.original.actions.join(", ") || "None yet"}</span> }),
            roleColumns.display({
              id: "act",
              header: "Actions",
              cell: (c) => {
                const r = c.row.original;
                return !r.built_in && r.active_flag === "Y" ? (
                  <ActionButton<unknown>
                    label="Disable"
                    title={`Disable ${r.name}`}
                    effect="Every binding of this role stops allowing anything on the next request."
                    endpoint="/roles/disable"
                    askReason={false}
                    body={() => ({ name: r.name })}
                    describe={done("Role disabled.")}
                    variant="danger"
                    size="sm"
                  />
                ) : null;
              },
            }),
          ]}
        />
      </Card>
      <WideAccess />
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>Access to {label} · {bindings.length}</CardTitle>
        <div className="flex flex-wrap items-end gap-2">
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
        columns={[
          bindingColumns.display({ id: "who", header: "Who", cell: (c) => <span className="font-medium">{who(c.row.original)}</span> }),
          bindingColumns.display({ id: "what", header: "Gets", cell: (c) => what(c.row.original) }),
          bindingColumns.display({ id: "where", header: "Where", cell: (c) => where(c.row.original) }),
          bindingColumns.display({
            id: "act",
            header: "Actions",
            cell: (c) => (
              <ActionButton<unknown>
                label="Revoke"
                title={`Revoke ${what(c.row.original)} from ${who(c.row.original)}`}
                effect={`Removes this binding on ${where(c.row.original)}.`}
                endpoint="/access/revocations"
                body={(reason) => revokeBody(c.row.original, reason)}
                describe={done("Access revoked.")}
                variant="danger"
                size="sm"
              />
            ),
          }),
        ]}
      />
    </Card>
  );
}
