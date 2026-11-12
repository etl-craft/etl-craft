import { createColumnHelper } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { Disclosure, DisclosureSummary } from "@/components/dropdown";
import { RunLabel } from "@/components/run-label";
import { StatusBadge } from "@/components/status";
import { When } from "@/components/when";
import { words } from "@/lib/labels";
import { runPath } from "@/lib/routes";
import type { AlertDelivery } from "@/lib/types";

const columns = createColumnHelper<AlertDelivery>();

/** Show delivery facts without fetching or rendering channel credentials. */
export function AlertDeliveries({ code, rows = [] }: { code: string; rows?: AlertDelivery[] }) {
  return <section aria-label="Alert delivery history" className="grid min-w-0 grid-cols-1 gap-2">
    <h3 className="text-sm font-semibold">Alert deliveries</h3>
    <DataTable label="Alert deliveries" data={rows} empty="No alert deliveries yet."
      nextStep="Ask an administrator to approve a channel, then configure an EMAIL_ALERT task with ALERT_CHANNEL and ALERT_ON."
      columns={[
        columns.display({ id: "delivery", header: "Delivery", size: 150, cell: c => {
          const row = c.row.original;
          return <div className="grid min-w-0 gap-1 whitespace-normal">
            <span className="font-medium">{row.channel}</span>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge quiet label={words(row.status)} status={row.status === "SENT" ? "SUCCESS" : row.status === "FAILED" ? "FAILED" : "QUEUED"} />
              {row.status_code !== null ? <span>{row.status_code}</span> : row.error_class ? <span>{row.error_class}</span> : null}
            </div>
            <Disclosure>
              <DisclosureSummary>Delivery details</DisclosureSummary>
              <div className="grid min-w-0 gap-2 py-2">
                <span>{words(row.trigger)} · attempt {row.attempt_number}</span>
                <span>Source run <RunLabel id={row.source_run_id} label={row.source_run_label} to={runPath(code, row.pipeline_code, row.source_run_id)} /></span>
                <span>Alert run <RunLabel id={row.alert_run_id} label={row.alert_run_label} to={runPath(code, row.pipeline_code, row.alert_run_id)} /></span>
              </div>
            </Disclosure>
          </div>;
        } }),
        columns.accessor("created_at", { header: "Time", size: 140, cell: c => <When iso={c.getValue()} /> }),
      ]} />
  </section>;
}
