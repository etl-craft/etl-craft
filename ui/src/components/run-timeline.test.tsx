import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RunTimeline } from "@/components/run-timeline";
import { getJson } from "@/lib/api";
import type { RunView, TimelineSegment } from "@/lib/types";

vi.mock("@/lib/api", async (original) => ({ ...await original<typeof import("@/lib/api")>(), getJson: vi.fn() }));
afterEach(() => vi.mocked(getJson).mockReset());

const segment = (values: Partial<TimelineSegment>): TimelineSegment => ({
  task_code: "LOAD", kind: "EXECUTION", started_at: "2026-03-01T09:00:00Z", ended_at: "2026-03-01T09:01:00Z",
  outcome: "SUCCESS", attempt_number: 1, deadline: null, ...values,
});

function show(timeline: TimelineSegment[], status: RunView["status"] = "SUCCESS") {
  vi.mocked(getJson).mockResolvedValue({ settings: { timezone: "UTC" } });
  const run = { status, end_date: "2026-03-01T09:10:00Z", timeline } as RunView;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><RunTimeline run={run} /></QueryClientProvider>);
}

it("draws each recorded kind on its task's row with its times and outcome", () => {
  show([
    segment({ task_code: null, kind: "GATE", started_at: "2026-03-01T08:59:30Z", ended_at: "2026-03-01T08:59:59Z", outcome: "SATISFIED", attempt_number: null }),
    segment({ kind: "QUEUE", started_at: "2026-03-01T08:59:59Z", ended_at: "2026-03-01T09:00:00Z" }),
    segment({}),
    segment({ task_code: "WAIT", kind: "EVENT", started_at: "2026-03-01T09:00:10Z", ended_at: null, outcome: "OPEN", attempt_number: null, deadline: "2026-03-01T10:00:00Z" }),
    segment({ task_code: "LATE", kind: "GATE", ended_at: "2026-03-01T09:05:00Z", outcome: "TIMED_OUT", attempt_number: null }),
  ]);
  expect(screen.getAllByRole("listitem").map((row) => row.textContent)).toEqual(expect.arrayContaining(["Pipeline gate", "LOAD", "WAIT", "LATE"]));
  expect(screen.getByRole("button", { name: /^Pipeline: Dependency gate .* Satisfied\.$/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /^LOAD, attempt 1: Queued for a slot/ })).toBeVisible();
  const open = screen.getByRole("button", { name: /^WAIT: Event wait from .* to still open, deadline .*Waiting\.$/ });
  expect(open).toHaveAttribute("data-open", "true");
  expect(screen.getByRole("button", { name: /^LATE: Dependency gate .* Timed out\.$/ })).toBeVisible();
  fireEvent.focus(open);
  expect(open).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(/^WAIT: Event wait from/, { selector: "p" })).toBeVisible();
  expect(screen.getByRole("list", { name: "Timeline key" })).toHaveTextContent("Event wait");
});

it("says a wait stopped with its run instead of drawing it as open", () => {
  show([segment({ task_code: "WAIT", kind: "EVENT", ended_at: null, outcome: "ENDED", attempt_number: null })], "CANCELLED");
  const bar = screen.getByRole("button", { name: /stopped with the run/ });
  expect(bar).not.toHaveAttribute("data-open");
});

it("says plainly when nothing has been recorded", () => {
  show([]);
  expect(screen.getByText("No queue, wait or execution has been recorded for this run.")).toBeVisible();
});
