import { Disclosure, DisclosureSummary } from "@/components/dropdown";
import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/when";
import { Download } from "lucide-react";
import * as React from "react";
import { Fact, FactList, Loading, Notice } from "@/components/common";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { getText, project } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";
import { words } from "@/lib/labels";
import type { AttemptView } from "@/lib/types";

const ROWS = [
  ["source_count", "Rows in"],
  ["insert_count", "Inserted"],
  ["update_count", "Updated"],
  ["delete_count", "Deleted"],
  ["rows_written", "Rows written"],
  ["reject_count", "Rejected"],
  ["duplicate_count", "Duplicates"],
  ["target_count", "Target rows"],
] as const satisfies readonly (readonly [keyof AttemptView, string])[];
const evidence = (kind: string | null, actor: string | null, reason: string | null) =>
  kind ? [words(kind), actor, reason].filter(Boolean).join(" · ") : "Not recorded";
const ERROR = /\b(ERROR|FATAL|CRITICAL|Traceback)\b/;
const WARNING = /\bWARN(ING)?\b/;
const LIVE = new Set(["QUEUED", "CLAIMED", "RUNNING"]);

/** An attempt's log, fetched on demand and kept fresh while the attempt is still running. */
export function AttemptLog({ code, attempt, open = false }: { code: string; attempt: Pick<AttemptView, "attempt_id" | "status">; open?: boolean }) {
  const [shown, setShown] = React.useState(open);
  const [wrap, setWrap] = React.useState(true);
  const log = useQuery({
    queryKey: ["log", code, attempt.attempt_id, attempt.status],
    queryFn: () => getText(`${project(code)}/attempts/${attempt.attempt_id}/log`),
    enabled: shown,
    refetchInterval: LIVE.has(attempt.status) ? 3_000 : false,
  });
  const lines = log.data?.split("\n") ?? [];
  const [find, setFind] = React.useState("");
  const [follow, setFollow] = React.useState(LIVE.has(attempt.status));
  const box = React.useRef<HTMLPreElement>(null);
  const needle = find.trim().toLowerCase();
  const matching = needle ? lines.filter((line) => line.toLowerCase().includes(needle)) : lines.slice(-400);
  const firstError = matching.findIndex((line) => ERROR.test(line));
  React.useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [follow, log.data]);
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" className="w-fit" onClick={() => setShown(!shown)} aria-expanded={shown}>
          {shown ? "Hide log" : "Show log"}
        </Button>
        {shown && log.isSuccess ? (
          <>
            <input type="search" aria-label="Find in log" placeholder="Find in log" value={find} onChange={(event) => setFind(event.target.value)} className="h-7 w-44 rounded-sm border border-border-strong bg-surface px-2 text-xs" />
            {needle ? <span className="text-xs text-muted">{matching.length} of {lines.length} lines</span> : null}
            <Button size="sm" disabled={firstError < 0} onClick={() => box.current?.querySelector(`[data-line="${firstError}"]`)?.scrollIntoView({ block: "center" })}>
              First error
            </Button>
            <Button size="sm" onClick={() => downloadFile(`attempt-${attempt.attempt_id}.log`, log.data, "text/plain;charset=utf-8")}>
              <Download className="size-4" aria-hidden /> Download log
            </Button>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={wrap} onChange={(event) => setWrap(event.target.checked)} /> Wrap lines
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={follow} onChange={(event) => setFollow(event.target.checked)} /> Follow
            </label>
          </>
        ) : null}
      </div>
      {shown && log.isPending ? <Loading what="log" /> : null}
      {shown && log.isError ? <Notice>{(log.error as Error).message}</Notice> : null}
      {shown && log.isSuccess ? (
        <>
          {!needle && lines.length > 400 ? <p className="m-0 text-xs text-muted">Showing the last 400 of {lines.length} lines; search or download the log for all of it.</p> : null}
          <pre ref={box} tabIndex={0} aria-label="Attempt log" className={cn("m-0 max-h-96 overflow-auto rounded-sm border border-border bg-surface-2 p-3 font-mono text-xs leading-5", wrap && "whitespace-pre-wrap break-words")}>
            {matching.map((line, i) => (
              <span key={i} data-line={i} className={cn("block", ERROR.test(line) ? "text-bad" : WARNING.test(line) && "text-warn")}>
                {line || " "}
              </span>
            ))}
          </pre>
        </>
      ) : null}
    </div>
  );
}

/** Everything recorded about one attempt: who ran it, when, what it wrote, how it ended, and its log. */
export function AttemptDetails({ code, attempt, heading, showLog = false }: { code: string; attempt: AttemptView; heading?: React.ReactNode; showLog?: boolean }) {
  return (
    <section className="grid gap-3" aria-label={`Attempt ${attempt.attempt_number}`}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="m-0 text-sm font-semibold">{heading ?? `Attempt ${attempt.attempt_number}`}</h3>
        <StatusBadge status={attempt.status} />
        <span className="num text-xs text-muted">id {attempt.attempt_id}</span>
      </div>
      {attempt.error_message ? <Notice mono>{attempt.error_message}</Notice> : null}
      <FactList className="gap-3 sm:grid-cols-4 lg:grid-cols-4">
        <Fact label="Started"><When iso={attempt.started_at} empty="Not started" /></Fact>
        <Fact label="Ended"><When iso={attempt.ended_at} empty="Not yet" /></Fact>
        <Fact label="Duration">{formatDuration(attempt.started_at, attempt.ended_at)}</Fact>
        {attempt.status === "FAILED" || attempt.status === "TIMED_OUT" || attempt.status === "LOST" ? (
          <Fact label="Failure">
            {[words(attempt.failure_class), attempt.failure_source, attempt.failure_code].filter(Boolean).join(" · ")}
          </Fact>
        ) : null}
        {/* Only what was measured: a count the handler does not report is left out, not shown as "Not measured". */}
        {ROWS.filter(([key]) => attempt[key] !== null).map(([key, label]) => (
          <Fact key={key} label={label}>{(attempt[key] as number).toLocaleString("en-GB")}</Fact>
        ))}
        {attempt.watermark_to ? (
          <Fact label="Watermark">
            <span className="break-all">{attempt.watermark_from ?? "start"} → {attempt.watermark_to}</span>
          </Fact>
        ) : null}
      </FactList>
      <Disclosure className="text-[13px]">
        <DisclosureSummary className="w-fit cursor-pointer text-xs font-medium text-muted hover:text-fg">Process details</DisclosureSummary>
        <FactList className="mt-3 gap-3 sm:grid-cols-4 lg:grid-cols-4">
          <Fact label="Queued"><When iso={attempt.queued_at} /></Fact>
          <Fact label="Agent">{attempt.owner_id ?? "Not claimed"}</Fact>
          <Fact label="Host">
            <span className="break-all">{attempt.host ?? "Not recorded"}{attempt.pid ? ` · PID ${attempt.pid}` : ""}</span>
          </Fact>
          <Fact label="Exit code">{attempt.exit_code ?? (attempt.ended_at ? "Not recorded" : "Still running")}</Fact>
          <Fact label="Retries on">{attempt.retry_on ? words(attempt.retry_on).toLowerCase() : "—"}</Fact>
          <Fact label="How the process ended">{evidence(attempt.process_evidence_kind, attempt.process_evidence_actor, attempt.process_evidence_reason)}</Fact>
          <Fact label="How the query ended">{evidence(attempt.query_evidence_kind, attempt.query_evidence_actor, attempt.query_evidence_reason)}</Fact>
        </FactList>
      </Disclosure>
      {attempt.log_path ? <AttemptLog code={code} attempt={attempt} open={showLog} /> : <p className="m-0 text-[13px] text-muted">No log was recorded for this attempt.</p>}
    </section>
  );
}
