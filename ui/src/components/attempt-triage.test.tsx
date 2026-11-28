import { fireEvent, render, screen } from "@testing-library/react";
import { AttemptStatistics, FailureSummary, MedianMark } from "@/components/attempt-triage";
import type { AttemptError, AttemptView } from "@/lib/types";

const anchor: AttemptError = {
  event: { sequence: 1, step: "Merge", error_class: "IntegrityError", exit_code: "SQL_GUARD", failure_class: "PERMANENT" },
  offset: 10, line: 4, state: "LIVE", text: "Duplicate key", message: null,
};
const attempt = {
  attempt_number: 2, status: "FAILED", failure_code: "23505", first_error: anchor,
  last_error: anchor, source_count: 1200, reject_count: 0, rows_written: null,
  started_at: "2026-11-01T00:00:03Z", queued_at: "2026-11-01T00:00:00Z",
  ended_at: "2026-11-01T00:00:05Z", peak_rss_bytes: null, cpu_seconds: 1,
} as AttemptView;

it.each(["RUNNING", "SUCCESS"])("keeps failure fields out of a %s try", status => {
  render(<FailureSummary attempt={{...attempt, status}} />);
  expect(screen.queryByText("23505", { exact: false })).toBeNull();
  expect(screen.queryByRole("region", { name: "Failure summary" })).toBeNull();
});

it.each([
  ["ARCHIVED", null, "Archived log"],
  ["EXPIRED", "Attempt 2 log expired on 2026-11-02", "expired on"],
  ["READ_FAILED", "Attempt 2 log could not be read.", "could not be read"],
  ["MISSING", "Location not recorded for attempt 2.", "Location not recorded"],
] as const)("reports %s without guessing an anchor", (state, message, label) => {
  const jump = vi.fn();
  render(<FailureSummary attempt={{ ...attempt, first_error: {...anchor, state, message}, last_error: null }} onLine={jump} />);
  expect(screen.getByText(label, {exact: false})).toBeInTheDocument();
  expect(screen.getByText("Last error was not recorded for try 2.")).toBeInTheDocument();
  expect(screen.getByRole("row", { name: /Native code 23505 23505/ })).toBeInTheDocument();
  const link = screen.queryByRole("button", { name: /Go to line 4/ });
  if (state === "ARCHIVED") {
    fireEvent.click(link!);
    expect(jump).toHaveBeenCalledWith(4);
  } else expect(link).toBeNull();
});

it("distinguishes absent from zero and derives throughput, queue time and CPU", () => {
  render(<AttemptStatistics attempt={attempt} now={0} metrics={{source_count: {median: 1_400_000, sample_size: 12}}} />);
  expect(screen.getByText("1.2k")).toBeInTheDocument();
  expect(screen.getByRole("row", { name: /Read 1.2k.*1.4M 12/ })).toBeInTheDocument();
  expect(screen.getByText("0")).toBeInTheDocument();
  expect(screen.getByText("600")).toBeInTheDocument();
  expect(screen.getByText("3s")).toBeInTheDocument();
  expect(screen.getByText("0.5 cores")).toBeInTheDocument();
  expect(screen.queryByText("Written")).toBeNull();
  expect(screen.queryByText("Peak memory")).toBeNull();
});

it("omits unknown throughput and metrics for a Python task without counts", () => {
  render(<AttemptStatistics attempt={{...attempt, source_count: null, reject_count: null, cpu_seconds: null}} now={0} />);
  expect(screen.queryByText("Rows a second")).toBeNull();
  expect(screen.queryByText("Read")).toBeNull();
  expect(screen.queryByText("Rejected")).toBeNull();
});

it.each([[3, 9, null], [3, 1, null], [0, 10, null], [3, 10, "▲"], [3, 0, "▼"]])(
  "uses strict thresholds for median %s and value %s", (median, value, glyph) => {
    render(<MedianMark value={value} sample={{median, sample_size: 12}} format={String} />);
    if (glyph) {
      const mark = screen.getByRole("button");
      expect(mark).toHaveTextContent(glyph);
      fireEvent.focus(mark);
      expect(screen.getByRole("tooltip")).toHaveTextContent("× median");
    } else expect(screen.queryByRole("button")).toBeNull();
  },
);
