import { ArrowUpRight, Box } from "lucide-react";
import * as React from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { edgeClass, solidClass, statusMeta } from "@/components/status";
import type { Graph } from "@/lib/types";
import { cn } from "@/lib/utils";

type Focus = "none" | "focus" | "lineage" | "dim";

export type Direction = "LR" | "TB";

interface TaskData extends Record<string, unknown> {
  label: string;
  vertical: boolean;
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
/** Top to bottom, a wave of many tasks wraps into rows of this many. */
const MAX_COLS = 3;
const GAP_ROW = 56;
const GAP_COL = 40;

const NODE_TONE: Record<Focus, string> = {
  none: "border-border-strong",
  focus: "border-accent ring-2 ring-accent",
  lineage: "border-accent",
  dim: "border-border opacity-40",
};

function Task({ data }: NodeProps<TaskNode>) {
  const plain = data.status === "";
  const { icon: Icon, label: statusLabel, spin } = plain ? { icon: Box, label: "", spin: false } : statusMeta(data.status);
  return (
    <div
      data-focus={data.focus}
      className={cn("flex h-[52px] w-[230px] items-center gap-2 rounded-sm border border-l-[4px] bg-surface pl-2.5 pr-2 text-[13px] transition-opacity", plain ? "border-l-border-strong" : edgeClass(data.status), NODE_TONE[data.focus])}
    >
      <Handle type="target" position={data.vertical ? Position.Top : Position.Left} className="!size-1.5 !border-0 !bg-border-strong" />
      <span className={cn("grid size-7 shrink-0 place-items-center rounded-sm", plain ? "bg-idle-bg text-idle" : solidClass(data.status))} title={statusLabel}>
        <Icon aria-hidden className={cn("size-4", spin && "animate-spin")} />
      </span>
      <span className="grid min-w-0 flex-1">
        <span className="line-clamp-2 break-all font-medium leading-tight" title={data.label}>{data.label}</span>
        {plain ? null : <span className="text-xs text-muted">{statusLabel}</span>}
      </span>
      <button
        type="button"
        aria-label={`Open ${data.label} details`}
        title="Open this task"
        className="nodrag nopan grid size-7 shrink-0 cursor-pointer place-items-center rounded-md border border-border-strong text-muted hover:border-accent hover:bg-surface-2 hover:text-accent"
        onClick={(event) => {
          event.stopPropagation();
          data.onOpen(data.label);
        }}
      >
        <ArrowUpRight aria-hidden className="size-4" />
      </button>
      <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} className="!size-1.5 !border-0 !bg-border-strong" />
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
  plain = false,
  direction: Direction = "LR",
): { nodes: TaskNode[]; edges: Edge[]; height: number; columns: number } {
  const lineage = focused ? lineageOf(graph, focused) : null;
  const stateOf = (code: string): Focus => (!lineage ? "none" : code === focused ? "focus" : lineage.has(code) ? "lineage" : "dim");
  // A wave of many tasks wraps into extra columns; every column is centred on the tallest one.
  const vertical = direction === "TB";
  const per = vertical ? MAX_COLS : MAX_ROWS;
  const rowsOf = (wave: string[]) => Math.min(wave.length, per);
  const tallest = Math.max(1, ...graph.waves.map(rowsOf));
  let column = 0;
  const nodes: TaskNode[] = graph.waves.flatMap((wave) => {
    const lift = ((tallest - rowsOf(wave)) * (vertical ? WIDTH + GAP_COL : HEIGHT + GAP_Y)) / 2;
    const placed = wave.map((code, index) => ({
      id: code,
      type: "task" as const,
      position: vertical
        ? { x: lift + (index % per) * (WIDTH + GAP_COL), y: (column + Math.floor(index / per)) * (HEIGHT + GAP_ROW) }
        : { x: (column + Math.floor(index / per)) * (WIDTH + GAP_X), y: lift + (index % per) * (HEIGHT + GAP_Y) },
      data: { label: code, vertical, status: statuses[code] ?? (plain ? "" : "QUEUED"), focus: stateOf(code), onOpen },
      draggable: false,
    }));
    column += Math.max(1, Math.ceil(wave.length / per));
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
  plain,
  fill,
  direction,
}: {
  graph: Graph;
  statuses: Record<string, string>;
  focused: string | null;
  onFocus: (task: string | null) => void;
  onOpen: (task: string) => void;
  /** Show task definitions only, with no run status. */
  plain?: boolean;
  /** Take the height of the container and keep the whole graph in view as it is resized. */
  fill?: boolean;
  /** Left to right or top to bottom; when omitted a filled graph picks the one that suits its pane's shape. */
  direction?: Direction;
}) {
  const frame = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  const [frameHeight, setFrameHeight] = React.useState(0);
  React.useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry?.contentRect.width ?? 0);
      setFrameHeight(entry?.contentRect.height ?? 0);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const flow = React.useRef<ReactFlowInstance | null>(null);
  const shown: Direction = direction ?? (fill && frameHeight > width ? "TB" : "LR");
  const { nodes, edges, height, columns } = layout(graph, statuses, focused, onOpen, plain, shown);
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
  // Resizing the pane refits the whole graph, so a divider drag never hides a task.
  React.useEffect(() => {
    if (fill && width > 0 && frameHeight > 0) void flow.current?.fitView({ padding: 0.08, minZoom: 0.15, maxZoom: 1.3 });
  }, [fill, width, frameHeight, shown]);
  // A graph wider than its card keeps readable boxes starting at the left; a small one is fitted whole.
  const wide = !fill && width > 0 && columns * (WIDTH + GAP_X) - GAP_X + 48 > width;
  return (
    <div ref={frame} style={fill ? undefined : { height }} role="group" aria-label="Task graph" className={cn("relative w-full", fill && "h-full min-h-64")}>
      {edges.length === 0 ? (
        <p className="absolute left-3 top-2 z-10 m-0 text-xs text-muted">No dependencies between these tasks: they can run at the same time.</p>
      ) : (
        <p className="absolute left-3 top-2 z-10 m-0 text-xs text-muted">
          {focused ? `Showing everything upstream and downstream of ${focused}. Click the background to clear.` : "Click a task to highlight its lineage."}
        </p>
      )}
      <ReactFlow
        key={`${wide ? "wide" : "fit"}:${shown}:${nodes.map((n) => n.id).join("|")}`}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView={!wide}
        fitViewOptions={fill ? { padding: 0.08, minZoom: 0.15, maxZoom: 1.3 } : { padding: 0.12, minZoom: 0.8, maxZoom: 1 }}
        defaultViewport={wide ? { x: 24, y: 40, zoom: 0.9 } : undefined}
        minZoom={fill ? 0.15 : 0.5}
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
