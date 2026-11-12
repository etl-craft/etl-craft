import { useMemo } from "react";
import { ActionButton } from "@/components/action-button";
import { DataTable, columnsOf } from "@/components/data-table";
import { FormAction, type FieldSpec } from "@/components/form-action";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { done, ListState, useAdminList } from "./shared";

type Channel = { channel_name: string; kind: string; url_secret: string; signing_secret: string; default_alert_on: string | null; active_flag: string };

export function AlertChannelsTab({ project }: { project: string }) {
  const query = useAdminList<{ channels: Channel[] }>("/api/v1/alert-channels", { project }, !!project);
  const fields: FieldSpec[] = [
    { name: "name", label: "Channel name", required: true },
    { name: "kind", label: "Kind", kind: "select", options: ["WEBHOOK", "SLACK"], required: true },
    { name: "url_secret", label: "URL variable name", required: true, help: "Reference only. Put the HTTPS webhook URL in the server's secret source." },
    { name: "signing_secret", label: "Signing key variable name", required: true, help: "Reference only. The secret value must contain at least 32 bytes." },
    { name: "default_alert_on", label: "Default events", initial: "FAILURE", help: "FAILURE, SLA_BREACH, LOST or GATE_WAIT_OVER_<minutes>, joined by |." },
  ];
  const columns = useMemo(() => columnsOf<Channel>([
        { id: "name", header: "Channel", value: c => c.channel_name },
        { id: "kind", header: "Kind", value: c => c.kind },
        { id: "events", header: "Default events", value: c => c.default_alert_on ?? "None" },
        { id: "url", header: "URL variable", value: c => c.url_secret },
        { id: "key", header: "Key variable", value: c => c.signing_secret },
        { id: "state", header: "State", value: c => c.active_flag === "Y" ? "Active" : "Disabled" },
        { id: "action", header: "Actions", value: c => c.channel_name, cell: c => c.active_flag === "Y" ? <ActionButton key={c.channel_name} label="Disable" title={`Disable ${c.channel_name}`} effect="Stops new alert admission and delivery; history stays." endpoint="/alert-channels/disable" projectCode={project} body={reason => ({ project, name: c.channel_name, reason })} describe={done("Channel disabled.")} variant="danger" size="sm" /> : null },
      ]), [project]);
  return <div className="grid min-w-0 grid-cols-1 gap-5">
    <ListState query={query} what="alert channels" />
    <Card className="min-w-0">
      <CardHeader><CardTitle>Alert channels · {project}</CardTitle>
        <FormAction label="Set channel" title="Set an alert channel" effect={`Creates or replaces and enables a channel in ${project}. Only administrators own routing, defaults and secret references. Developers select its approved name.`} endpoint="/alert-channels" projectCode={project} extra={{ project }} fields={fields} describe={done("Channel saved.")} variant="primary" />
      </CardHeader>
      <DataTable label="Alert channels" data={query.data?.channels ?? []} nextStep="Set a channel above, then select its name through the alert task's ALERT_CHANNEL parameter." columns={columns} />
    </Card>
  </div>;
}
