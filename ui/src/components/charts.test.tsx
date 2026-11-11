import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { HBars, KpiTile } from "@/components/charts";

describe("the dashboard charts", () => {
  it("uses numbers for sparse series and keeps names linked", () => {
    render(
      <MemoryRouter>
        <HBars label="Rows" empty="Nothing." rows={[{ label: "a", value: 10, to: "/a" }, { label: "b", value: 0 }]} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "a" }).getAttribute("href")).toBe("/a");
    expect(screen.queryByRole("listitem")).toBeNull();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
  });

  it("says why there is nothing to rank", () => {
    render(<HBars label="Rows" empty="Nothing ran." rows={[]} />);
    expect(screen.getByText("Nothing ran.")).toBeTruthy();
  });

  it("shows a headline with its context", () => {
    render(<KpiTile label="Success rate" value="97%" hint="2 failed" tone="bad" />);
    expect(screen.getByText("97%").className).toContain("text-bad");
    expect(screen.getByText("2 failed")).toBeTruthy();
  });
});

// Exercise the dashboard's public composition, including padding days without runs.
it.each([1, 2, 3, 4])("shows a %i-day dashboard window as dated counts and durations", async (length) => {
  const { Overview } = await import("@/components/overview");
  const end = new Date(Date.UTC(2026, 10, 10 + length)).toISOString();
  const day = new Date(Date.UTC(2026, 10, 9 + length)).toISOString().slice(0, 10);
  const total = { pipeline_code: null, runs: length, succeeded: length - 1, failed: 1, finished: length, in_progress: 0, success_rate: (length - 1) / length, average_seconds: 6.4, longest_seconds: 6.4, sla_breached: 0, attempts: length, retries: 0, lost_attempts: 0, rows_written: null, rows_per_second: null, average_wait_seconds: null, average_run_seconds: null };
  render(<MemoryRouter><Overview code="demo" d={{ window_start: "2026-11-10T00:00:00Z", window_end: end, pipelines: [], total, per_pipeline: [], days: [{ day, runs: length, succeeded: length - 1, failed: 1, average_seconds: 6.4 }], tasks: [], failures: [], rules: [], latest: [], gaps: [], gaps_compared_at: null, schema_check_schedule: null, schema_check_on_demand: false }} /></MemoryRouter>);
  const summary = screen.getByRole("region", { name: "Runs per day" });
  expect(summary.querySelectorAll("dt")).toHaveLength(length);
  expect(summary.querySelectorAll("svg")).toHaveLength(0);
  expect(summary.textContent).toContain(`${length} ${length === 1 ? "run" : "runs"} · ${length - 1} succeeded · 1 failed`);
  expect(summary.textContent).toContain("Average duration 6.4s");
  expect(summary.querySelector(`time[datetime="${day}"]`)).toBeTruthy();
  expect(summary.textContent?.match(/No finished runs/g) ?? []).toHaveLength(length - 1);
});
