import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Link } from "react-router-dom";
import { Fact, FactList, Loading, Notice, PageHeader } from "@/components/common";
import { DataTable } from "@/components/data-table";
import { EnvironmentBadge } from "@/components/environment-badge";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useHealth, useTimezone } from "@/hooks";
import { getJson } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { agentsPath, runsPath } from "@/lib/routes";
import type { About, AgentsView, ControllerVersion, PoolCapacity, ProjectCounts } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const controllers = createColumnHelper<ControllerVersion>();
const pools = createColumnHelper<PoolCapacity>();
const projects = createColumnHelper<ProjectCounts>();

export function System() {
  useDocumentTitle("System health");
  const tz = useTimezone();
  const about = useQuery({ queryKey: ["about"], queryFn: () => getJson<About>("/api/v1/about"), refetchInterval: 15_000 });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => getJson<AgentsView>("/api/v1/agents"), refetchInterval: 15_000 });
  const health = useHealth();
  const live = about.data?.controllers ?? [];
  const mixed = [...new Set(live.map((c) => c.version))].filter((v) => v !== about.data?.package_version);
  const active = (agents.data?.agents ?? []).filter((a) => a.status === "ACTIVE");
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="System health" subtitle="This page reads the Engine DB, so seeing it means the Engine DB answered." />
      {about.isError ? <Notice>{(about.error as Error).message}</Notice> : null}
      {about.isPending ? <Loading what="system health" /> : null}
      {about.data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Controllers</CardTitle>
              {live.length ? <StatusBadge status="ACTIVE" label={`Running · ${live.length}`} /> : <StatusBadge status="FAILED" label="Not running" />}
            </CardHeader>
            {live.length ? (
              <DataTable
                label="Controllers"
                data={live}
                columns={[
                  controllers.accessor("controller_id", { header: "Controller" }),
                  controllers.accessor("version", { header: "Version" }),
                  controllers.accessor("heartbeat_at", { header: "Last heartbeat", cell: (c) => <span className="num whitespace-nowrap">{formatTime(c.getValue(), tz)}</span> }),
                ]}
              />
            ) : (
              <div className="p-4">
                <Notice>
                  No controller has sent a heartbeat in the last minute, so schedules, retries and queued tasks are not starting. Start one on the host with <code className="font-mono">etl-craft controller</code>.
                </Notice>
              </div>
            )}
            {mixed.length ? (
              <div className="p-4 pt-0">
                <Notice>
                  Controllers run {mixed.join(", ")} while this server runs {about.data.package_version}. Finish the upgrade so every process runs one version.
                </Notice>
              </div>
            ) : null}
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Engine DB</CardTitle>
                <StatusBadge status="ACTIVE" label="Answering" />
              </CardHeader>
              <FactList className="p-4 sm:grid-cols-2 lg:grid-cols-2">
                <Fact label="Schema version">{about.data.schema_version ?? "Not recorded"}</Fact>
                <Fact label="Package version">{about.data.package_version}</Fact>
              </FactList>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Agents</CardTitle>
                <Link className="text-sm text-accent hover:underline" to={agentsPath}>
                  Open agents
                </Link>
              </CardHeader>
              <div className="grid gap-3 p-4">
                {agents.data ? (
                  <p className="m-0 text-sm">
                    {active.length ? <StatusBadge status="ACTIVE" label={`${active.length} active`} /> : <span className="text-muted">None active. Tasks wait for an agent only where the deployment uses agents.</span>}
                    {agents.data.agents.length - active.length > 0 ? <span className="ml-2 text-muted">{agents.data.agents.length - active.length} draining or gone</span> : null}
                  </p>
                ) : (
                  <Loading what="agents" />
                )}
              </div>
              {agents.data?.pools.length ? (
                <DataTable
                  label="Agent pools"
                  data={agents.data.pools}
                  columns={[
                    pools.accessor("pool", { header: "Pool" }),
                    pools.accessor("agents", { header: "Agents" }),
                    pools.display({ id: "cpu", header: "Free CPU", cell: (c) => `${c.row.original.free_cpu.toFixed(1)} of ${c.row.original.advertised_cpu.toFixed(1)}` }),
                    pools.display({ id: "mem", header: "Free memory", cell: (c) => `${c.row.original.free_memory_mb} of ${c.row.original.advertised_memory_mb} MB` }),
                  ]}
                />
              ) : null}
            </Card>
          </div>
        </>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>Projects, last 24 hours</CardTitle>
        </CardHeader>
        <DataTable
          label="Projects"
          data={health.data?.projects ?? []}
          empty={health.isSuccess ? "No projects you can view." : undefined}
          columns={[
            projects.accessor("project", { header: "Project", cell: (c) => <Link className="font-medium text-accent hover:underline" to={runsPath(c.getValue())}>{c.getValue()}</Link> }),
            projects.display({ id: "env", header: "Environment", cell: (c) => <EnvironmentBadge env={{ type: c.row.original.environment_type, name: c.row.original.environment_name }} /> }),
            projects.accessor("running", { header: "Running" }),
            projects.accessor("queued_tasks", { header: "Queued tasks" }),
            projects.accessor("failed", { header: "Failed", cell: (c) => (c.getValue() ? <StatusBadge status="FAILED" label={String(c.getValue())} /> : 0) }),
            projects.accessor("sla_misses", { header: "SLA misses" }),
          ]}
        />
        <p className="m-0 border-t border-border p-3 text-xs text-muted">
          Warehouse connections are checked by each task and by <code className="font-mono">etl-craft doctor</code> on the host; schema checks show on each project's Insights page.
        </p>
      </Card>
    </div>
  );
}
