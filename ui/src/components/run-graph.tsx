import { ArrowUpRight } from "lucide-react";
import * as React from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { statusMeta, toneClass } from "@/components/status";
import type { Graph } from "@/lib/types";
import { cn } from "@/lib/utils";

type Focus = "none" | "focus" | "lineage" | "dim";

interface TaskData extends Record<string, unknown> {
  label: string;
  status: string;
  focus: Focus;
  onOpen: (task: string) => void;
}
type TaskNode = Node<TaskData, "task">;

const WIDTH = 230;
const HEIGHT = 52;
const GAP_X = 70;
const GAP_Y = 24;
const MAX_ROWS = 4;

const NODE_TONE: Record<Focus, string> = {
  none: "border-border-strong",
  focus: "border-accent ring-2 ring-accent",
  lineage: "border-accent",
  dim: "border-border opacity-40",
};

function Task({ data }: NodeProps<TaskNode>) {
  const { icon: Icon, label: statusLabel, spin } = statusMeta(data.status);
  return (
    <div
      data-focus={data.focus}
      className={cn("flex h-[52px] w-[230px] items-center gap-2 rounded-md border bg-surface pl-2.5 pr-2 text-[13px] shadow-sm transition-opacity", NODE_TONE[data.focus])}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-border-strong" />
      <span className={cn("grid size-7 shrink-0 place-items-center rounded-full", toneClass(data.status))} title={statusLabel}>
        <Icon aria-hidden className={cn("size-4", spin && "animate-spin")} />
      </span>
      <span className="grid min-w-0 flex-1">
        <span className="truncate font-medium" title={data.label}>{data.label}</span>
        <span className="text-xs text-muted">{statusLabel}</span>
      </span>
      <button
        type="button"
        aria-label={`Open ${data.label} details`}
        title="Open status, attempts and log"
        className="nodrag nopan grid size-7 shrink-0 cursor-pointer place-items-center rounded-md border border-border-strong text-muted hover:border-accent hover:bg-surface-2 hover:text-accent"
        onClick={(event) => {
          event.stopPropagation();
          data.onOpen(data.label);
        }}
      >
        <ArrowUpRight aria-hidden className="size-4" />
      </button>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-border-strong" />
    </div>
  );
}

const nodeTypes = { task: Task };

/** The task with everything upstream and downstream of it. */
export function lineageOf(graph: Graph, task: string): Set<string> {
  const downstream = new Map<string, string[]>();
  for (const [target, deps] of Object.entries(graph.depends_on))
    for (const [source] of deps) downstream.set(source, [...(downstream.get(source) ?? []), target]);
  const walk = (start: string, next: (id: string) => string[]) => {
    const seen = new Set<string>();
    const queue = [start];
    for (let id = queue.pop(); id !== undefined; id = queue.pop()) {
      for (const other of next(id)) {
        if (seen.has(other)) continue;
        seen.add(other);
        queue.push(other);
      }
    }
    return seen;
  };
  const up = walk(task, (id) => (graph.depends_on[id] ?? []).map(([source]) => source));
  const down = walk(task, (id) => downstream.get(id) ?? []);
  return new Set([task, ...up, ...down]);
}

/** One column per dependency wave; edges come from the pipeline's stored dependency rows. */
export function layout(
  graph: Graph,
  statuses: Record<string, string>,
  focused: string | null,
  onOpen: (task: string) => void = () => undefined,
): { nodes: TaskNode[]; edges: Edge[]; height: number; columns: number } {
  const lineage = focused ? lineageOf(graph, focused) : null;
  const stateOf = (code: string): Focus => (!lineage ? "none" : code === focused ? "focus" : lineage.has(code) ? "lineage" : "dim");
  // A wave of many tasks wraps into extra columns; every column is centred on the tallest one.
  const rowsOf = (wave: string[]) => Math.min(wave.length, MAX_ROWS);
  const tallest = Math.max(1, ...graph.waves.map(rowsOf));
  let column = 0;
  const nodes: TaskNode[] = graph.waves.flatMap((wave) => {
    const lift = ((tallest - rowsOf(wave)) * (HEIGHT + GAP_Y)) / 2;
    const placed = wave.map((code, index) => ({
      id: code,
      type: "task" as const,
      position: { x: (column + Math.floor(index / MAX_ROWS)) * (WIDTH + GAP_X), y: lift + (index % MAX_ROWS) * (HEIGHT + GAP_Y) },
      data: { label: code, status: statuses[code] ?? "QUEUED", focus: stateOf(code), onOpen },
      draggable: false,
    }));
    column += Math.max(1, Math.ceil(wave.length / MAX_ROWS));
    return placed;
  });
  const edges: Edge[] = Object.entries(graph.depends_on).flatMap(([task, deps]) =>
    deps.map(([dependency, condition]) => {
      const on = lineage ? lineage.has(dependency) && lineage.has(task) : false;
      const color = on ? "var(--accent)" : "var(--muted)";
      return {
        id: `${dependency}->${task}`,
        source: dependency,
        target: task,
        label: condition && condition !== "SUCCESS" ? condition.toLowerCase() : undefined,
        style: {
          stroke: color,
          strokeWidth: on ? 2.4 : 1.6,
          opacity: lineage && !on ? 0.25 : 1,
          ...(condition && condition !== "SUCCESS" ? { strokeDasharray: "6 4" } : {}),
        },
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color },
        labelBgStyle: { fill: "var(--surface)", stroke: "var(--border-strong)" },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 4,
        labelStyle: { fill: "var(--fg)", fontSize: 12, fontWeight: 500 },
      };
    }),
  );
  return { nodes, edges, height: Math.min(460, Math.max(200, tallest * (HEIGHT + GAP_Y) + 40)), columns: column };
}

export function RunGraph({
  graph,
  statuses,
  focused,
  onFocus,
  onOpen,
}: {
  graph: Graph;
  statuses: Record<string, string>;
  focused: string | null;
  onFocus: (task: string | null) => void;
  onOpen: (task: string) => void;
}) {
  const frame = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  React.useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry?.contentRect.width ?? 0));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const flow = React.useRef<ReactFlowInstance | null>(null);
  const { nodes, edges, height, columns } = layout(graph, statuses, focused, onOpen);
  // Bring a focused task into view when it is off-screen; leave the view alone when it is visible.
  React.useEffect(() => {
    const instance = flow.current;
    const node = nodes.find((n) => n.id === focused);
    if (!instance || !node || width === 0) return;
    const { x, zoom } = instance.getViewport();
    const left = node.position.x * zoom + x;
    if (left >= 0 && left + WIDTH * zoom <= width) return;
    void instance.setCenter(node.position.x + WIDTH / 2, node.position.y + HEIGHT / 2, { zoom, duration: 250 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused]);
  // A graph wider than its card keeps readable boxes starting at the left; a small one is fitted whole.
  const wide = width > 0 && columns * (WIDTH + GAP_X) - GAP_X + 48 > width;
  return (
    <div ref={frame} style={{ height }} role="group" aria-label="Task graph" className="relative w-full">
      {edges.length === 0 ? (
        <p className="absolute left-3 top-2 z-10 m-0 text-xs text-muted">No dependencies between these tasks: they can run at the same time.</p>
      ) : (
        <p className="absolute left-3 top-2 z-10 m-0 text-xs text-muted">
          {focused ? `Showing everything upstream and downstream of ${focused}. Click the background to clear.` : "Click a task to highlight its lineage."}
        </p>
      )}
      <ReactFlow
        key={wide ? "wide" : "fit"}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView={!wide}
        fitViewOptions={{ padding: 0.12, minZoom: 0.8, maxZoom: 1 }}
        defaultViewport={wide ? { x: 24, y: 40, zoom: 0.9 } : undefined}
        minZoom={0.5}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        onNodeClick={(_, node) => onFocus(node.id === focused ? null : node.id)}
        onInit={(instance) => {
          flow.current = instance as unknown as ReactFlowInstance;
        }}
        onPaneClick={() => onFocus(null)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} color="var(--border)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
