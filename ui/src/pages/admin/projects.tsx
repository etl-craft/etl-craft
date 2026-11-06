import { createColumnHelper } from "@tanstack/react-table";
import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { EnvironmentBadge } from "@/components/environment-badge";
import { FormAction, type FieldSpec } from "@/components/form-action";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import type { PoolRow, ProjectRow } from "@/lib/types";
import { done, ListState, useAdminList } from "./shared";

const LISTING = "the administration page";
const columns = createColumnHelper<ProjectRow>();
const pools = createColumnHelper<PoolRow>();

const projectFields = (code: boolean): FieldSpec[] => [
  { name: "project", label: "Project code", required: true },
  { name: "name", label: "Name" },
  { name: "timezone", label: "Timezone", hint: "UTC or Europe/London" },
  { name: "default_pool", label: "Default pool" },
  { name: "max_running_tasks", label: "Max running tasks", kind: "number" },
  { name: "environment_type", label: "Environment", kind: "select", options: ["DEV", "SIT", "UAT", "PROD", "SANDBOX", "CUSTOM"], blank: code ? "Default" : "Keep" },
  { name: "environment_name", label: "Environment name" },
  { name: "governance", label: "Governance", kind: "select", options: ["STRICT", "RELAXED"], blank: code ? "Default" : "Keep" },
  { name: "schema_check_schedule", label: "Schema check schedule (cron, or none)" },
  { name: "schema_check_on_demand", label: "On-demand schema checks", kind: "select", options: ["Y", "N"], blank: code ? "Default" : "Keep" },
];

export function ProjectsTab() {
  const list = useAdminList<{ projects: ProjectRow[] }>("/api/v1/projects", { reason: LISTING });
  const rows = list.data?.projects ?? [];
  return (
    <div className="grid gap-5">
      <ListState query={list} what="projects" />
      <Card>
        <CardHeader>
          <CardTitle>Projects · {rows.length}</CardTitle>
          <div className="flex flex-wrap gap-2">
            <FormAction label="Add project" title="Add a project" effect="Creates the project. Fields left empty take their defaults." endpoint="/projects" variant="primary" describe={done("Project added.")} fields={projectFields(true)} />
            <FormAction label="Change project" title="Change a project" effect="Fields left empty keep their current value." endpoint="/projects/set" describe={done("Project changed.")} fields={projectFields(false)} />
          </div>
        </CardHeader>
        <DataTable
          label="Projects"
          data={rows}
          columns={[
            columns.accessor("project", { header: "Project", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            columns.accessor("name", { header: "Name" }),
            columns.display({ id: "env", header: "Environment", cell: (c) => <EnvironmentBadge env={{ type: c.row.original.environment_type, name: c.row.original.environment_name }} /> }),
            columns.accessor("governance", { header: "Governance" }),
            columns.accessor("default_pool", { header: "Default pool" }),
            columns.accessor("max_running_tasks", { header: "Max tasks" }),
            columns.display({ id: "schema", header: "Schema checks", cell: (c) => (c.row.original.schema_check_schedule ? <code className="font-mono text-xs">{c.row.original.schema_check_schedule}</code> : "Not scheduled") }),
            columns.display({ id: "state", header: "State", cell: (c) => <StatusBadge status={c.row.original.active_flag === "Y" ? "ACTIVE" : "DISABLED"} /> }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) =>
                c.row.original.active_flag === "Y" ? (
                  <ActionButton<unknown> label="Disable" title={`Disable ${c.row.original.project}`} effect="Stops this project's pipelines running; its metadata and history stay." endpoint="/projects/disable" body={(reason) => ({ project: c.row.original.project, reason })} describe={done("Project disabled.")} variant="danger" size="sm" />
                ) : null,
            }),
          ]}
        />
      </Card>
    </div>
  );
}

export function PoolsTab() {
  const list = useAdminList<{ pools: PoolRow[] }>("/api/v1/pools", { reason: LISTING });
  const rows = list.data?.pools ?? [];
  const fields: FieldSpec[] = [
    { name: "name", label: "Pool name", required: true },
    { name: "description", label: "Description" },
  ];
  return (
    <div className="grid gap-5">
      <ListState query={list} what="pools" />
      <Card>
        <CardHeader>
          <CardTitle>Pools · {rows.length}</CardTitle>
          <div className="flex flex-wrap gap-2">
            <FormAction label="Add pool" title="Add a pool" effect="Creates a pool that projects and tasks can name." endpoint="/pools" variant="primary" describe={done("Pool added.")} fields={fields} />
            <FormAction label="Change description" title="Change a pool's description" effect="Only the description changes." endpoint="/pools/set" describe={done("Pool changed.")} fields={fields} />
          </div>
        </CardHeader>
        <DataTable
          label="Pools"
          data={rows}
          columns={[
            pools.accessor("name", { header: "Pool", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            pools.accessor("description", { header: "Description", cell: (c) => c.getValue() ?? "" }),
            pools.display({ id: "state", header: "State", cell: (c) => <StatusBadge status={c.row.original.active_flag === "Y" ? "ACTIVE" : "DISABLED"} /> }),
            pools.display({
              id: "act",
              header: "Actions",
              cell: (c) =>
                c.row.original.active_flag === "Y" ? (
                  <ActionButton<unknown> label="Disable" title={`Disable ${c.row.original.name}`} effect="Stops placing work in this pool; refused while a project or task still uses it." endpoint="/pools/disable" body={(reason) => ({ name: c.row.original.name, reason })} describe={done("Pool disabled.")} variant="danger" size="sm" />
                ) : null,
            }),
          ]}
        />
      </Card>
    </div>
  );
}
