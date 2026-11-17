import { createColumnHelper } from "@tanstack/react-table";
import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import type { Binding, RoleView } from "@/lib/types";
import { done, ListState, useAdminList } from "./shared";

const columns = createColumnHelper<Binding>();
export const AUDIENCES = ["viewer", "operator", "developer"];
export const ENVIRONMENTS = ["DEV", "SIT", "UAT", "PROD", "SANDBOX", "CUSTOM"];
export const who = (b: Binding) => (b.group ? `group ${b.group}` : b.account ? `account ${b.account}` : `every ${b.audience}`);
export const where = (b: Binding) =>
  b.pipeline ? `pipeline ${b.pipeline}` : b.tag ? `tag ${b.tag}` : b.scope === "DEPLOYMENT" ? "every project" : b.scope === "ENVIRONMENT" ? `every ${b.environment} project` : `project ${b.project}`;
export const what = (b: Binding) => b.role ?? `command ${b.action}`;

/** The roles a binding can give, for the grant forms. */
export function useRoleNames() {
  const roles = useAdminList<{ roles: RoleView[] }>("/api/v1/roles");
  return (roles.data?.roles ?? []).filter((r) => r.active_flag === "Y").map((r) => r.name);
}

export function revokeBody(b: Binding, reason: string) {
  return {
    project: b.scope === "PROJECT" ? b.project : null,
    environment: b.scope === "ENVIRONMENT" ? b.environment : null,
    deployment: b.scope === "DEPLOYMENT",
    group: b.group,
    account: b.account,
    audience: b.audience,
    pipeline: b.pipeline,
    tag: b.tag,
    role: b.role,
    action: b.action,
    reason,
  };
}

/** Bindings that apply to one project: its own, its environment's and the deployment's. */
export function AccessTab({ project, projects, pipeline }: { project: string; projects: string[]; pipeline?: string }) {
  const list = useAdminList<{ bindings: Binding[]; effective: [string, string | null, string[]][] }>("/api/v1/access/grants", { project, pipeline }, !!project);
  const roles = useRoleNames();
  const bindings = (list.data?.bindings ?? []).filter((b) => b.active_flag === "Y");
  const canManage = !pipeline || list.data?.effective.some(([code, level]) => code === pipeline && level === "CAN_MANAGE");
  return (
    <div className="grid min-w-0 grid-cols-1 gap-5">
      <ListState query={list} what="access" />
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Access to {pipeline || project || "a project"} · {bindings.length}</CardTitle>
          {canManage ? (
            <FormAction
              projectCode={pipeline ? project : undefined}
              label="Grant access"
              title="Grant access"
              effect={`Give one account, group or audience a role or one command on ${pipeline ? `pipeline ${pipeline}` : `project ${project}, or one of its pipelines or tags`}.`}
              endpoint="/access/grants"
              variant="primary"
              describe={done("Access granted.")}
              extra={{ project, ...(pipeline ? { pipeline } : {}) }}
              fields={[
                { name: "account", label: "Account" },
                { name: "group", label: "Group" },
                { name: "audience", label: "Every account with role", kind: "select", options: AUDIENCES, blank: "None" },
                { name: "role", label: "Role", kind: "select", options: roles, blank: "None (give one command)" },
                { name: "action", label: "Or one command, such as run" },
                ...(!pipeline ? [{ name: "pipeline", label: "Pipeline" }, { name: "tag", label: "Tag" }] : []),
              ]}
            />
          ) : null}
        </CardHeader>
        <DataTable
          find
          label="Access bindings"
          data={bindings}
          nextStep={pipeline ? "Ask a pipeline manager to grant access here." : "Grant an account, group or audience a role or one command above."}
          empty={list.isSuccess ? "No access yet." : projects.length ? undefined : "No projects."}
          columns={[
            columns.display({ id: "who", header: "Who", cell: (c) => <span className="font-medium">{who(c.row.original)}</span> }),
            columns.display({ id: "what", header: "Gets", cell: (c) => what(c.row.original) }),
            columns.display({ id: "where", header: "Where", cell: (c) => where(c.row.original) }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) => {
                const b = c.row.original;
                return canManage && b.scope === "PROJECT" ? (
                  <ActionButton<unknown>
                    projectCode={pipeline ? project : undefined}
                    label="Revoke"
                    title={`Revoke ${what(b)} from ${who(b)}`}
                    effect={`Removes this binding on ${where(b)}; access from other bindings stays.`}
                    endpoint="/access/revocations"
                    body={(reason) => revokeBody(b, reason)}
                    describe={done("Access revoked.")}
                    variant="danger"
                    size="sm"
                  />
                ) : null;
              },
            }),
          ]}
        />
      </Card>
    </div>
  );
}
