import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { AttemptDetails } from "@/components/attempt-details";
import type { AttemptView } from "@/lib/types";

it("keeps the original failure diagnostics only in process details", () => {
  const attempt: AttemptView = {
    attempt_id: 9, attempt_number: 1, pipeline_run_id: 4, task_run_id: 7,
    status: "FAILED", owner_id: null, queued_at: null, claimed_at: null,
    started_at: null, ended_at: null, host: null, pid: null, exit_code: 1,
    source_count: null, target_count: null, insert_count: null, update_count: null,
    delete_count: null, rows_written: null, reject_count: null, duplicate_count: null,
    watermark_from: null, watermark_to: null, error_message: "The source refused the connection.",
    failure_class: "UNKNOWN", failure_source: "PYTHON_TASK", failure_code: "RuntimeError",
    retry_on: null, retry_reason: null, retryable: false, log_path: null,
    process_evidence_kind: null, process_evidence_actor: null, process_evidence_reason: null,
    query_evidence_kind: null, query_evidence_actor: null, query_evidence_reason: null,
  };
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { enabled: false } } })}><AttemptDetails code="demo" attempt={attempt} /></QueryClientProvider>);
  const details = screen.getByText("Process details").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  for (const raw of ["UNKNOWN", "PYTHON_TASK", "RuntimeError"]) {
    expect(within(details).getByText(raw, { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText(raw, { exact: true })).toHaveLength(1);
  }
  expect(screen.queryByText("Failure", { exact: true })).toBeNull();
  expect(screen.getByRole("alert")).toHaveTextContent(attempt.error_message!);
});
