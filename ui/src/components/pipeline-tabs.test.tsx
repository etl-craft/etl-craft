import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DetailsTab, OverviewTab } from "@/components/pipeline-tabs";
import type { Graph, Pipeline, RunView } from "@/lib/types";

const pipeline = { pipeline_code: "REF", pipeline_name: "REF", refresh_type: "FULL", run_schedule: null, sla_in_hours: null, paused: null, tags: [], task_pauses: [], next_run: null, schedule_problem: null, recent_runs: [], description: "Copies the reference tables." } as unknown as Pipeline;
const graph: Graph = { waves: [["copy_agents"], ["copy_types"]], conditional: [], depends_on: { copy_types: [["copy_agents", "SUCCESS"]] } };
const run = (id: number, status: string, hoursAgo: number): RunView => {
  const start = new Date(Date.now() - hoursAgo * 3_600_000);
  return { pipeline_code: "REF", pipeline_run_id: id, status, start_date: start.toISOString(), end_date: new Date(start.getTime() + 60_000).toISOString() } as unknown as RunView;
};

function shown(node: React.ReactNode, definitions: Record<string, string | undefined> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  for (const [task, doc] of Object.entries(definitions)) client.setQueryData(["task", "demo", "REF", task], { task_code: task, handler: "SQL", parameters: doc ? { DOCUMENTATION: doc } : {}, merge_key: [], merge_columns: [] });
  client.setQueryData(["whoami", null], { name: "owner", role: "admin", settings: { timezone: "UTC", time_display: "UTC" } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("the pipeline details tab", () => {
  it("lists the task definitions and points to the catalog for what the pipeline is for", () => {
    shown(<DetailsTab code="demo" pipeline={pipeline} graph={graph} />, { copy_agents: "Copies the agents table.", copy_types: undefined });
    expect(screen.getByRole("link", { name: /Open the documentation in the catalog/ }).getAttribute("href")).toBe("/projects/demo/catalog/pipelines/REF");
    expect(screen.getByText("copy_agents")).toBeTruthy();
    expect(screen.getByText("copy_types")).toBeTruthy();
  });
});

describe("the pipeline overview tab", () => {
  it("counts the runs and failures inside the window only", () => {
    shown(<OverviewTab code="demo" pipeline={pipeline} runs={[run(4, "FAILED", 2), run(3, "SUCCESS", 5), run(2, "FAILED", 30), run(1, "SUCCESS", 60)]} />);
    const tile = (label: string) => screen.getByText(label).parentElement!;
    expect(within(tile("Runs")).getByText("2")).toBeTruthy(); // the last 24 hours
    expect(within(tile("Failed runs")).getByText("1")).toBeTruthy();
    expect(within(tile("Success rate")).getByText("50%")).toBeTruthy();
    expect(screen.getByRole("link", { name: "#4" })).toBeTruthy(); // the failure, linked to its run
  });
});
