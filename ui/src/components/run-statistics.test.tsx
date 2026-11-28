import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { RunStatistics, useRunStatistics } from "@/components/run-statistics";
import type { RunView } from "@/lib/types";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
});

it("sorts the entire run in the address, pages at 100 and uses compact card labels", () => {
  const query = new QueryClient({defaultOptions: {queries: {staleTime: Infinity}}});
  const end = "2026-11-01T00:00:03Z";
  const attempt = { attempt_id: 20, attempt_number: 2, status: "SUCCESS", started_at: "2026-11-01T00:00:00Z", ended_at: end, reject_count: 0 };
  const tasks = Array.from({length: 101}, (_, index) => ({
    task_code: `load-${index.toString().padStart(3, "0")}`, status: "SUCCESS",
    attempts: [{...attempt, attempt_id: 19, attempt_number: 1, status: "FAILED", reject_count: 3}, {...attempt, source_count: index}],
    duration: {median: 1, sample_size: 12},
  }));
  query.setQueryData(["run-statistics", "demo", 3, end], {tasks});
  const run = {pipeline_run_id: 3, end_date: end} as RunView;
  function Address() { return <output>{useLocation().search}</output>; }
  function Statistics() { return <RunStatistics code="demo" run={run} stats={useRunStatistics("demo", run)} onTask={vi.fn()} />; }
  render(<MemoryRouter initialEntries={["/?view=statistics&statisticsSort=read:desc"]}><QueryClientProvider client={query}>
    <Address /><Statistics />
  </QueryClientProvider></MemoryRouter>);
  const table = screen.getByRole("table", {name: "Run statistics"});
  expect(table).toHaveClass("stacked-table");
  expect(within(table).getAllByRole("row")).toHaveLength(101);
  expect(within(table).getAllByRole("row")[1]).toHaveTextContent("load-100");
  expect(screen.queryByRole("button", {name: /reject breakdown/i})).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "Next"}));
  expect(screen.getByText(/statisticsPage=2/)).toBeInTheDocument();
  expect(within(table).getAllByRole("row")).toHaveLength(2);
  expect(within(table).getByText("load-000")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Earlier tries" }));
  expect(within(table).getByRole("button", {name: "Try 1"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: /reject breakdown/i})).toBeNull();
  fireEvent.change(screen.getByLabelText("Sort statistics by"), {target: {value: "duration"}});
  expect(screen.getByText(/statisticsSort=duration%3Aasc/)).toBeInTheDocument();
  expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
});

it.each([null, "2026-11-02T08:00:00Z"])("states only recorded target-retention evidence (%s)", (date) => {
  const query = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, refetchOnMount: false } } });
  const end = "2026-11-01T00:00:03Z";
  const run = {pipeline_run_id: 3, pipeline_code: "P", end_date: end} as RunView;
  query.setQueryData(["run-statistics", "demo", 3, end], { tasks: [{
    task_code: "load", duration: { median: null, sample_size: 0 }, status: "FAILED",
    attempts: [{ attempt_id: 20, attempt_number: 1, status: "FAILED", reject_count: 3 }],
  }] });
  query.setQueryData(["reject-breakdown", "demo", 3, "load"], {
    rows: [], recorded_count: 3, reject_table: "warehouse.main.sales__rejects", retention_removed_at: date,
  });
  function Statistics() { return <RunStatistics code="demo" run={run} stats={useRunStatistics("demo", run)} onTask={vi.fn()} />; }
  render(<MemoryRouter><QueryClientProvider client={query}><Statistics /></QueryClientProvider></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", {name: "Reject breakdown for load"}));
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveTextContent("Reject breakdown unavailable. This task recorded 3 rejects; their rows are no longer in warehouse.main.sales__rejects.");
  if (date) {
    expect(dialog).toHaveTextContent("Retention last removed rows from this target on");
    expect(dialog.querySelector("time")).toHaveAttribute("datetime", date);
  } else expect(dialog).not.toHaveTextContent("Retention last removed rows");
  expect(dialog).not.toHaveTextContent(/expired|replaced/);
});
