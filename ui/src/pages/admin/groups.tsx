import { createColumnHelper } from "@tanstack/react-table";
import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import type { Group } from "@/lib/types";
import { done, ListState, useAdminList } from "./shared";

const columns = createColumnHelper<Group>();

export function GroupsTab() {
  const list = useAdminList<{ groups: Group[] }>("/api/v1/groups");
  const groups = list.data?.groups ?? [];
  return (
    <div className="grid gap-5">
      <ListState query={list} what="groups" />
      <Card>
        <CardHeader>
          <CardTitle>Groups · {groups.length}</CardTitle>
          <div className="flex flex-wrap gap-2">
            <FormAction
              label="Add group"
              title="Add a group"
              effect="Creates an empty group that grants can name."
              endpoint="/groups"
              askReason={false}
              variant="primary"
              describe={done("Group added.")}
              fields={[
                { name: "name", label: "Group name", required: true },
                { name: "description", label: "Description" },
              ]}
            />
            <FormAction
              label="Add member"
              title="Add a member"
              effect="Gives the account the access the group is granted."
              endpoint="/groups/members"
              askReason={false}
              describe={done("Member added.")}
              fields={[
                { name: "name", label: "Group", kind: "select", options: groups.filter((g) => g.active_flag === "Y").map((g) => g.name), required: true },
                { name: "account", label: "Account name", required: true },
              ]}
            />
          </div>
        </CardHeader>
        <DataTable
          find
          label="Groups"
          data={groups}
          empty={list.isSuccess ? "No groups yet." : undefined}
          columns={[
            columns.accessor("name", { header: "Group", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            columns.accessor("description", { header: "Description", cell: (c) => c.getValue() ?? "" }),
            columns.display({
              id: "members",
              header: "Members",
              cell: (c) =>
                c.row.original.members.length ? (
                  <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                    {c.row.original.members.map((m) => (
                      <li key={m} className="flex items-center gap-1">
                        {m}
                        <ActionButton<unknown> label="Remove" title={`Remove ${m} from ${c.row.original.name}`} effect="Access granted through the group ends for this account." endpoint="/groups/members/remove" askReason={false} body={() => ({ name: c.row.original.name, account: m })} describe={done(`${m} removed.`)} size="sm" variant="ghost" />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-muted">None</span>
                ),
            }),
            columns.display({ id: "state", header: "State", cell: (c) => <StatusBadge status={c.row.original.active_flag === "Y" ? "ACTIVE" : "DISABLED"} /> }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) =>
                c.row.original.active_flag === "Y" ? (
                  <ActionButton<unknown> label="Disable" title={`Disable ${c.row.original.name}`} effect="Stops this group granting access; its grants and history stay." endpoint="/groups/disable" askReason={false} body={() => ({ name: c.row.original.name })} describe={done("Group disabled.")} variant="danger" size="sm" />
                ) : null,
            }),
          ]}
        />
      </Card>
    </div>
  );
}
