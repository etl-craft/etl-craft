import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { OverviewTab, pipelineTabs } from "@/components/pipeline-tabs";
import type { Pipeline, RunView } from "@/lib/types";

const pipeline = { pipeline_code: "REF", pipeline_name: "REF", refresh_type: "FULL", run_schedule: null, sla_in_hours: null, paused: null, tags: [], task_pauses: [], next_run: null, schedule_problem: null, recent_runs: [], description: "Copies the reference tables." } as unknown as Pipeline;
const run = (id: number, status: string, hoursAgo: number): RunView => {
  const start = new Date(Date.now() - hoursAgo * 3_600_000);
  return { pipeline_code: "REF", pipeline_run_id: id, status, start_date: start.toISOString(), end_date: new Date(start.getTime() + 60_000).toISOString() } as unknown as RunView;
};

function shown(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(["whoami", null], { name: "owner", role: "admin", settings: { timezone: "UTC", time_display: "UTC" } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it("has one tab definition with only the kept workspace views",()=>{
  expect(pipelineTabs().map(tab=>tab.id)).toEqual(expect.arrayContaining(["overview","runs","audit","access"]));
  for(const removed of ["tasks","details","calendar"])expect(pipelineTabs().some(tab=>tab.id===removed)).toBe(false);
  expect(pipelineTabs(8,"label").find(tab=>tab.id==="run")?.label).toBe("Run #8 · label");
});

describe("the pipeline overview tab", () => {
  it("counts the runs and failures inside the window only", () => {
    shown(<OverviewTab code="demo" pipeline={pipeline} runs={[run(4, "FAILED", 2), run(3, "SUCCESS", 5), run(2, "FAILED", 30), run(1, "SUCCESS", 60)]} />);
    const tile = (label: string) => screen.getByText(label).parentElement!;
    expect(within(tile("Runs")).getByText("2")).toBeTruthy(); // the last 24 hours
    expect(within(tile("Failed runs")).getByText("1")).toBeTruthy();
    expect(within(tile("Success rate")).getByText("50%")).toBeTruthy();
    expect(screen.queryByRole("region",{name:"Recent failures"})).toBeNull();
    expect(screen.queryByRole("region",{name:"Latest run durations"})).toBeNull();
    expect(screen.getByRole("link",{name:"Open run history"})).toHaveAttribute("href","/projects/demo/pipelines/REF?tab=runs");
    expect(screen.getByRole("link",{name:"Run history by day"})).toHaveAttribute("href","/projects/demo/scheduled?pipeline=REF");
    expect(screen.getByRole("link",{name:"About this pipeline in the catalog"})).toHaveAttribute("href","/projects/demo/catalog/pipelines/REF");
  });
});
