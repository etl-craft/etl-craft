import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { compactCount } from "@/components/attempt-triage";
import { Loading, Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Table, Td, Th } from "@/components/ui/table";
import { useTimezone } from "@/hooks";
import { getJson, project } from "@/lib/api";
import { formatTime } from "@/lib/format";
import type { RunView } from "@/lib/types";

type Breakdown = { rows: { reason: string; count: number }[]; reject_table: string | null; recorded_count: number; retention_removed_at: string | null };

export function RejectBreakdown({ code, run, task, close }: { code: string; run: RunView; task: string; close: () => void }) {
  const title = useId();
  const timezone = useTimezone();
  const result = useQuery({
    queryKey: ["reject-breakdown", code, run.pipeline_run_id, task],
    staleTime: 0,
    queryFn: () => getJson<Breakdown>(`${project(code)}/reject-breakdown`, { pipeline_code: run.pipeline_code, run_id: run.pipeline_run_id, task_code: task }),
  });
  const data = result.data;
  return <Dialog open onClose={close} labelledBy={title}>
    <div className="grid gap-3 p-4">
      <h2 id={title} className="font-semibold">Reject breakdown · {task}</h2>
      {result.isPending ? <Loading what="reject breakdown" /> : null}
      {result.isError ? <Notice>{result.error.message}</Notice> : null}
      {data?.rows.length ? <Table unwrapped aria-label="Rejected rows by reason" className="stacked-table evidence-table table-fixed tabular-nums">
        <colgroup><col /><col className="w-20" /></colgroup>
        <thead><tr><Th scope="col">Reason</Th><Th scope="col" className="text-right">Rows</Th></tr></thead>
        <tbody>{data.rows.map(row => <tr key={row.reason}>
          <th scope="row" className="text-left font-medium">{row.reason}</th>
          <Td data-label="Rows" className="text-right">{compactCount(row.count)}</Td>
        </tr>)}</tbody>
      </Table> : data ? <p>
        Reject breakdown unavailable.{data.reject_table && data.recorded_count > 0 ? <> This task recorded {data.recorded_count.toLocaleString("en-GB")} rejects; their rows are no longer in {data.reject_table}.</> : null}
        {data.retention_removed_at ? <> Retention last removed rows from this target on <time dateTime={data.retention_removed_at}>{formatTime(data.retention_removed_at, timezone)}</time>.</> : null}
      </p> : null}
      <Button className="justify-self-end" onClick={close}>Close</Button>
    </div>
  </Dialog>;
}
