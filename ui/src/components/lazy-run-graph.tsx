import { lazy, Suspense } from "react";
import { Loading } from "@/components/common";
import type { RunGraph as Graph } from "@/components/run-graph";

const GraphView = lazy(() => import("@/components/run-graph").then((module) => ({ default: module.RunGraph })));

/** Load the graph library only when a graph is opened. */
export function RunGraph(props: React.ComponentProps<typeof Graph>) {
  return <Suspense fallback={<Loading what="graph" />}><GraphView {...props} /></Suspense>;
}
