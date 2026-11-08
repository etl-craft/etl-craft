import { createColumnHelper } from "@tanstack/react-table";
import * as React from "react";
import { Notice } from "@/components/common";
import { ActionButton } from "@/components/action-button";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { StatusBadge } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useTimezone } from "@/hooks";
import { formatTime } from "@/lib/format";
import type { TokenRow } from "@/lib/types";
import { done, ListState, ROLES, useAdminList } from "./shared";

const columns = createColumnHelper<TokenRow>();

export function TokensTab() {
  const tz = useTimezone();
  const list = useAdminList<{ tokens: TokenRow[] }>("/api/v1/tokens");
  const [created, setCreated] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const when = (value: string | null, none: string) => (value ? <span className="num whitespace-nowrap">{formatTime(value, tz)}</span> : none);
  return (
    <div className="grid gap-5">
      <ListState query={list} what="tokens" />
      {created ? (
        <Notice info className="grid gap-2">
          <span>This token is shown once. Store it in your secret manager now.</span>
          <code className="break-all font-mono text-xs">{created}</code>
          <span className="flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(created).then(() => setCopied(true));
              }}
            >
              {copied ? "Copied" : "Copy token"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCreated(null)}>
              I have stored it
            </Button>
          </span>
        </Notice>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>API tokens · {list.data?.tokens.length ?? 0}</CardTitle>
          <FormAction<{ token: string }>
            label="Create token"
            title="Create an API token"
            effect="The token is shown once, on this page."
            endpoint="/tokens"
            askReason={false}
            variant="primary"
            describe={() => "Token created."}
            onDone={(r) => {
              setCopied(false);
              setCreated(r.token);
            }}
            fields={[
              { name: "name", label: "Name", required: true },
              { name: "role", label: "Role", kind: "select", options: ROLES },
              { name: "expires", label: "Expires after", hint: "365d", initial: "365d" },
            ]}
          />
        </CardHeader>
        <DataTable
          find
          label="API tokens"
          data={list.data?.tokens ?? []}
          empty={list.isSuccess ? "No tokens." : undefined}
          columns={[
            columns.accessor("name", { header: "Name", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            columns.accessor("token_kind", { header: "Kind" }),
            columns.accessor("role", { header: "Role" }),
            columns.display({ id: "created", header: "Created", cell: (c) => <>{when(c.row.original.created_at, "")} <span className="text-muted">by {c.row.original.created_by}</span></> }),
            columns.accessor("expires_at", { header: "Expires", cell: (c) => when(c.getValue(), "Never") }),
            columns.accessor("last_used_at", { header: "Last used", cell: (c) => when(c.getValue(), "Never") }),
            columns.display({ id: "state", header: "State", cell: (c) => <StatusBadge status={c.row.original.revoked_at ? "REVOKED" : "ACTIVE"} /> }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) =>
                c.row.original.revoked_at ? null : (
                  <ActionButton<unknown> label="Revoke" title={`Revoke ${c.row.original.name}`} effect="Stops this token working at once; clients using it must sign in again." endpoint="/tokens/revoke" askReason={false} body={() => ({ token_id: c.row.original.token_id })} describe={done("Token revoked.")} variant="danger" size="sm" />
                ),
            }),
          ]}
        />
      </Card>
    </div>
  );
}
