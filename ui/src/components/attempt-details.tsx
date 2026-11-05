import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { Fact, FactList, Loading, Notice } from "@/components/common";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { useTimezone } from "@/hooks";
import { getText, project } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import type { AttemptView } from "@/lib/types";

const count = (value: number | null) => (value === null ? "Not measured" : value.toLocaleString("en-GB"));
const evidence = (kind: string | null, actor: string | null, reason: string | null) =>
  kind ? [kind, actor, reason].filter(Boolean).join(" · ") : "Not classified";
const LIVE = new Set(["QUEUED", "CLAIMED", "RUNNING"]);

/** An attempt's log, fetched on demand and kept fresh while the attempt is still running. */
export function AttemptLog({ code, attempt, open = false }: { code: string; attempt: Pick<AttemptView, "attempt_id" | "status">; open?: boolean }) {
  const [shown, setShown] = React.useState(open);
  const log = useQuery({
    queryKey: ["log", code, attempt.attempt_id, attempt.status],
    queryFn: () => getText(`${project(code)}/attempts/${attempt.attempt_id}/log`),
    enabled: shown,
    refetchInterval: LIVE.has(attempt.status) ? 3_000 : false,
  });
  const lines = log.data?.split("\n") ?? [];
  return (
    <div className="grid gap-2">
      <Button size="sm" className="w-fit" onClick={() => setShown(!shown)} aria-expanded={shown}>
        {shown ? "Hide log" : "Show log"}
      </Button>
      {shown && log.isPending ? <Loading what="log" /> : null}
      {shown && log.isError ? <Notice>{(log.error as Error).message}</Notice> : null}
      {shown && log.isSuccess ? (
        <>
          {lines.length > 400 ? <p className="m-0 text-xs text-muted">Showing the last 400 of {lines.length} lines.</p> : null}
          <pre tabIndex={0} aria-label="Attempt log" className="m-0 max-h-96 overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-xs leading-5">
            {lines.slice(-400).join("\n")}
          </pre>
        </>
      ) : null}
    </div>
  );
}

/** Everything recorded about one attempt: who ran it, when, what it wrote, how it ended, and its log. */
export function AttemptDetails({ code, attempt, heading, showLog = false }: { code: string; attempt: AttemptView; heading?: React.ReactNode; showLog?: boolean }) {
  const tz = useTimezone();
  return (
    <section className="grid gap-3" aria-label={`Attempt ${attempt.attempt_number}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="m-0 text-sm font-semibold">{heading ?? `Attempt ${attempt.attempt_number}`}</h3>
        <StatusBadge status={attempt.status} />
        <span className="num text-xs text-muted">id {attempt.attempt_id}</span>
      </div>
      {attempt.error_message ? <Notice mono>{attempt.error_message}</Notice> : null}
      <FactList className="gap-3 sm:grid-cols-4 lg:grid-cols-4">
        <Fact label="Queued">{formatTime(attempt.queued_at, tz)}</Fact>
        <Fact label="Started">{formatTime(attempt.started_at, tz)}</Fact>
        <Fact label="Ended">{formatTime(attempt.ended_at, tz)}</Fact>
        <Fact label="Duration">{formatDuration(attempt.started_at, attempt.ended_at)}</Fact>
        <Fact label="Owner">{attempt.owner_id ?? "Not claimed"}</Fact>
        <Fact label="Host">
          <span className="break-all">{attempt.host ?? "Not recorded"}{attempt.pid ? ` · PID ${attempt.pid}` : ""}</span>
        </Fact>
        <Fact label="Exit code">{attempt.exit_code ?? "None yet"}</Fact>
        <Fact label="Retry on">{attempt.retry_on ?? "—"}</Fact>
        <Fact label="Rows in">{count(attempt.source_count)}</Fact>
        <Fact label="Inserted">{count(attempt.insert_count)}</Fact>
        <Fact label="Updated">{count(attempt.update_count)}</Fact>
        <Fact label="Deleted">{count(attempt.delete_count)}</Fact>
        <Fact label="Rows written">{count(attempt.rows_written)}</Fact>
        <Fact label="Rejected">{count(attempt.reject_count)}</Fact>
        <Fact label="Duplicates">{count(attempt.duplicate_count)}</Fact>
        <Fact label="Target rows">{count(attempt.target_count)}</Fact>
        {attempt.watermark_to ? (
          <Fact label="Watermark">
            <span className="break-all">{attempt.watermark_from ?? "start"} → {attempt.watermark_to}</span>
          </Fact>
        ) : null}
        {attempt.status === "FAILED" ? (
          <Fact label="Failure">
            {attempt.failure_class}
            {attempt.failure_source ? ` · ${attempt.failure_source}` : ""}
            {attempt.failure_code ? ` · ${attempt.failure_code}` : ""}
          </Fact>
        ) : null}
        <Fact label="Process ending evidence">{evidence(attempt.process_evidence_kind, attempt.process_evidence_actor, attempt.process_evidence_reason)}</Fact>
        <Fact label="Query ending evidence">{evidence(attempt.query_evidence_kind, attempt.query_evidence_actor, attempt.query_evidence_reason)}</Fact>
      </FactList>
      {attempt.log_path ? <AttemptLog code={code} attempt={attempt} open={showLog} /> : <p className="m-0 text-[13px] text-muted">No log was recorded for this attempt.</p>}
    </section>
  );
}
