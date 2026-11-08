import { createColumnHelper } from "@tanstack/react-table";
import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import type { Grant } from "@/lib/types";
import { done, ListState, ROLES, useAdminList } from "./shared";

const columns = createColumnHelper<Grant>();
const PERMISSIONS = ["CAN_VIEW", "CAN_RUN", "CAN_MANAGE"];
const who = (g: Grant) => (g.group ? `group ${g.group}` : g.account ? `account ${g.account}` : `role ${g.role}`);
const on = (g: Grant) => (g.pipeline ? `pipeline ${g.pipeline}` : g.tag ? `tag ${g.tag}` : "the whole project");

export function AccessTab({ project, projects }: { project: string; projects: string[] }) {
  const list = useAdminList<{ grants: Grant[] }>("/api/v1/access/grants", { project }, !!project);
  const grants = (list.data?.grants ?? []).filter((g) => g.active_flag === "Y");
  return (
    <div className="grid gap-5">
      <ListState query={list} what="grants" />
      <Card>
        <CardHeader>
          <CardTitle>Access to {project || "a project"} · {grants.length}</CardTitle>
          <FormAction
            label="Grant access"
            title="Grant access"
            effect="Choose one of group, account or role; and one pipeline or tag, or neither for the whole project."
            endpoint="/access/grants"
            variant="primary"
            describe={done("Access granted.")}
            extra={{ project }}
            fields={[
              { name: "group", label: "Group" },
              { name: "account", label: "Account" },
              { name: "role", label: "Role", kind: "select", options: ROLES, blank: "None" },
              { name: "pipeline", label: "Pipeline" },
              { name: "tag", label: "Tag" },
              { name: "permission", label: "Permission", kind: "select", options: PERMISSIONS, required: true },
            ]}
          />
        </CardHeader>
        <DataTable
          find
          label="Access grants"
          data={grants}
          empty={list.isSuccess ? "No grants yet." : projects.length ? undefined : "No projects."}
          columns={[
            columns.display({ id: "who", header: "Who", cell: (c) => <span className="font-medium">{who(c.row.original)}</span> }),
            columns.display({ id: "on", header: "On", cell: (c) => on(c.row.original) }),
            columns.accessor("permission", { header: "Permission" }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) => {
                const g = c.row.original;
                return (
                  <ActionButton<unknown>
                    label="Revoke"
                    title={`Revoke ${who(g)}`}
                    effect={`Removes this grant on ${on(g)}; access from other grants stays.`}
                    endpoint="/access/revocations"
                    body={(reason) => ({ project: g.project, group: g.group, account: g.account, role: g.role, pipeline: g.pipeline, tag: g.tag, permission: g.permission, reason })}
                    describe={done("Grant revoked.")}
                    variant="danger"
                    size="sm"
                  />
                );
              },
            }),
          ]}
        />
      </Card>
    </div>
  );
}
