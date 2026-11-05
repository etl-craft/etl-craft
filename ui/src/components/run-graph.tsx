import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { statusMeta, toneClass } from "@/components/status";
import type { Graph } from "@/lib/types";
import { cn } from "@/lib/utils";

interface TaskData extends Record<string, unknown> {
  label: string;
  status: string;
  selected: boolean;
}
type TaskNode = Node<TaskData, "task">;

const WIDTH = 210;
const HEIGHT = 52;
const GAP_X = 70;
const GAP_Y = 24;
const MAX_ROWS = 4;

function Task({ data }: NodeProps<TaskNode>) {
  const { icon: Icon, label: statusLabel, spin } = statusMeta(data.status);
  return (
    <div
      className={cn(
        "flex h-[52px] w-[210px] items-center gap-2 rounded-md border bg-surface px-2.5 text-[13px] shadow-sm",
        data.selected ? "border-accent ring-2 ring-accent" : "border-border-strong",
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-border-strong" />
      <span className={cn("grid size-7 shrink-0 place-items-center rounded-full", toneClass(data.status))} title={statusLabel}>
        <Icon aria-hidden className={cn("size-4", spin && "animate-spin")} />
      </span>
      <span className="grid min-w-0">
        <span className="truncate font-medium">{data.label}</span>
        <span className="text-xs text-muted">{statusLabel}</span>
      </span>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-border-strong" />
    </div>
  );
}

const nodeTypes = { task: Task };

/** One column per dependency wave; edges come from the pipeline's stored dependency rows. */
export function layout(graph: Graph, statuses: Record<string, string>, selected: string | null): { nodes: TaskNode[]; edges: Edge[]; height: number } {
  // A wave of many tasks wraps into extra columns so the graph stays readable at a glance.
  let column = 0;
  let tallest = 1;
  const nodes: TaskNode[] = graph.waves.flatMap((wave) => {
    const placed = wave.map((code, index) => ({
      id: code,
      type: "task" as const,
      position: { x: (column + Math.floor(index / MAX_ROWS)) * (WIDTH + GAP_X), y: (index % MAX_ROWS) * (HEIGHT + GAP_Y) },
      data: { label: code, status: statuses[code] ?? "QUEUED", selected: code === selected },
      draggable: false,
    }));
    column += Math.max(1, Math.ceil(wave.length / MAX_ROWS));
    tallest = Math.max(tallest, Math.min(wave.length, MAX_ROWS));
    return placed;
  });
  const edges: Edge[] = Object.entries(graph.depends_on).flatMap(([task, deps]) =>
    deps.map(([dependency, condition]) => ({
      id: `${dependency}->${task}`,
      source: dependency,
      target: task,
      label: condition && condition !== "SUCCESS" ? condition.toLowerCase() : undefined,
      style: condition && condition !== "SUCCESS" ? { strokeDasharray: "5 4" } : undefined,
    })),
  );
  return { nodes, edges, height: Math.min(460, Math.max(200, tallest * (HEIGHT + GAP_Y) + 40)) };
}

export function RunGraph({
  graph,
  statuses,
  selected,
  onSelect,
}: {
  graph: Graph;
  statuses: Record<string, string>;
  selected: string | null;
  onSelect: (task: string) => void;
}) {
  const { nodes, edges, height } = layout(graph, statuses, selected);
  return (
    <div style={{ height }} role="group" aria-label="Task graph" className="w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={(_, node) => onSelect(node.id)}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
      >
        <Background gap={20} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
