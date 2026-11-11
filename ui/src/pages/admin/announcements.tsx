import { createColumnHelper } from "@tanstack/react-table";
import { When } from "@/components/when";
import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import type { Announcement } from "@/lib/types";
import { done, ListState, useAdminList } from "./shared";

const columns = createColumnHelper<Announcement>();

export function AnnouncementsTab() {
  const list = useAdminList<{ announcements: Announcement[] }>("/api/v1/announcements", { all: true });
  const rows = list.data?.announcements ?? [];
  return (
    <div className="grid gap-5">
      <ListState query={list} what="announcements" />
      <Card>
        <CardHeader>
          <CardTitle>Announcements · {rows.length}</CardTitle>
          <FormAction
            label="Post announcement"
            title="Post an announcement"
            effect="Shows a banner on every page until it ends."
            endpoint="/announcements"
            variant="primary"
            describe={done("Announcement posted.")}
            fields={[
              { name: "message", label: "Message", kind: "textarea", required: true },
              { name: "level", label: "Level", kind: "select", options: ["INFO", "WARNING", "CRITICAL"] },
              { name: "starts_at", label: "Starts (browser local time; empty: now)", kind: "datetime-local" },
              { name: "ends_at", label: "Ends (browser local time; empty: until ended)", kind: "datetime-local" },
            ]}
          />
        </CardHeader>
        <DataTable
          label="Announcements"
          data={rows}
          nextStep="Post an announcement above to inform people who sign in."
          empty={list.isSuccess ? "No announcements yet." : undefined}
          columns={[
            columns.accessor("level", { header: "Level", cell: (c) => c.getValue().charAt(0) + c.getValue().slice(1).toLowerCase() }),
            columns.accessor("message", { header: "Message" }),
            columns.display({ id: "shows", header: "Shows", cell: (c) => <span className="whitespace-nowrap"><When iso={c.row.original.starts_at} /> → <When iso={c.row.original.ends_at} empty="until ended" /></span> }),
            columns.accessor("created_by", { header: "Posted by" }),
            columns.display({ id: "state", header: "State", cell: (c) => (c.row.original.ended_at ? <StatusBadge quiet status="ENDED" label={`Ended by ${c.row.original.ended_by}`} /> : <StatusBadge quiet status="ACTIVE" label="Posted" />) }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) =>
                c.row.original.ended_at ? null : (
                  <ActionButton<unknown> label="End" title="End announcement" effect="Takes this announcement down now." endpoint="/announcements/end" body={(reason) => ({ announcement_id: c.row.original.announcement_id, reason })} describe={done("Announcement ended.")} size="sm" />
                ),
            }),
          ]}
        />
      </Card>
    </div>
  );
}
