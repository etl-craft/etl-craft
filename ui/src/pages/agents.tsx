import { useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { Loading, Notice, PageHeader } from "@/components/common";
import { RowActions, type RowAction } from "@/components/row-actions";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useRoleAtLeast, useTimezone } from "@/hooks";
import { getJson } from "@/lib/api";
import { formatTime } from "@/lib/format";
import type { AgentRow, AgentsView } from "@/lib/types";
import { useDocumentTitle } from "@/title";

const columns = createColumnHelper<AgentRow>();
const reply = (r: { message?: string }) => r.message ?? "Command sent to the agent.";

const command = (agent: AgentRow, name: string, label: string, effect: string, danger?: boolean): RowAction => ({
  label,
  title: `${label} agent ${agent.agent_id}`,
  effect: `${effect} Agent ${agent.agent_id} on ${agent.host}.`,
  endpoint: "/agents/commands",
  body: () => ({ agent_id: agent.agent_id, command: name }),
  describe: reply,
  askReason: false,
  danger,
});

export function Agents() {
  useDocumentTitle("Agents");
  const tz = useTimezone();
  const may = useRoleAtLeast("operator");
  const list = useQuery({ queryKey: ["agents"], queryFn: () => getJson<AgentsView>("/api/v1/agents"), refetchInterval: 10_000 });
  const rows = list.data?.agents ?? [];
  return (
    <div className="grid grid-cols-1 gap-5">
      <PageHeader title="Agents" subtitle="Worker processes that claim tasks, by pool" />
      {list.isError ? <Notice>{(list.error as Error).message}</Notice> : null}
      {list.isPending ? <Loading what="agents" /> : null}
      <Card>
        <CardHeader>
          <CardTitle>Registered agents · {rows.length}</CardTitle>
        </CardHeader>
        <DataTable find
          label="Agents"
          data={rows}
          empty={list.isSuccess ? "No agents have registered. Start one with etl-craft agent and an agent token. Deployments that run tasks on the controller's host do not use agents." : undefined}
          columns={[
            columns.accessor("agent_id", { header: "Agent" }),
            columns.accessor("pool", { header: "Pool" }),
            columns.accessor("host", { header: "Host" }),
            columns.accessor("version", { header: "Version" }),
            columns.accessor("status", { header: "State", cell: (c) => <StatusBadge status={c.getValue()} /> }),
            columns.accessor("heartbeat_at", { header: "Last heartbeat", cell: (c) => <span className="num whitespace-nowrap">{formatTime(c.getValue(), tz)}</span> }),
            columns.display({ id: "attempts", header: "Running attempts", cell: (c) => c.row.original.attempts.length }),
            columns.display({ id: "free", header: "Free CPU / memory", cell: (c) => `${c.row.original.free_cpu.toFixed(1)} / ${c.row.original.free_memory_mb} MB` }),
            columns.display({ id: "pending", header: "Pending commands", cell: (c) => c.row.original.pending_commands.map((p) => p.command).join(", ") || "None" }),
            ...(may
              ? [
                  columns.display({
                    id: "act",
                    header: "Actions",
                    cell: (c) => {
                      const a = c.row.original;
                      return (
                        <RowActions
                          name={`agent ${a.agent_id}`}
                          actions={[
                            ...(a.status === "ACTIVE" ? [command(a, "DRAIN", "Drain", "Stops this agent claiming new tasks; its running tasks finish.")] : []),
                            ...(a.status === "DRAINING" ? [command(a, "RESUME", "Resume", "Lets this agent claim new tasks again.")] : []),
                            ...(a.status !== "GONE" ? [command(a, "STOP", "Stop", "Stops the agent process; its running attempts are stopped and retried under their retry rules.", true)] : []),
                          ]}
                        />
                      );
                    },
                  }),
                ]
              : []),
          ]}
        />
      </Card>
    </div>
  );
}
