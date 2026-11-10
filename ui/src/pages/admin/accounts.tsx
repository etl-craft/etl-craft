import { EmptyState } from "@/components/common";
import { words } from "@/lib/labels";
import { createColumnHelper } from "@tanstack/react-table";
import { When } from "@/components/when";
import { DataTable } from "@/components/data-table";
import { FormAction } from "@/components/form-action";
import { RowActions } from "@/components/row-actions";
import { StatusBadge } from "@/components/status";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { useIdentity } from "@/hooks";
import type { Account } from "@/lib/types";
import { done, ListState, ROLES, useAdminList } from "./shared";

const columns = createColumnHelper<Account>();

export function AccountsTab() {
  const me = useIdentity().data?.name;
  const list = useAdminList<{ accounts: Account[] }>("/api/v1/accounts");
  const accounts = list.data?.accounts ?? [];
  const names = accounts.map((a) => a.name);
  return (
    <div className="grid gap-5">
      <ListState query={list} what="accounts" />
      <Card>
        <CardHeader>
          <CardTitle>Accounts · {accounts.length}</CardTitle>
          <div className="flex flex-wrap gap-2">
            <FormAction
              label="Add account"
              title="Add an account"
              effect="Creates the account. A user signs in with the temporary password and must change it."
              endpoint="/accounts"
              askReason={false}
              variant="primary"
              describe={done("Account added.")}
              fields={[
                { name: "name", label: "Account name", required: true },
                { name: "role", label: "Role", kind: "select", options: ROLES },
                { name: "kind", label: "Kind", kind: "select", options: ["USER", "SERVICE"] },
                { name: "first_name", label: "First name" },
                { name: "last_name", label: "Last name" },
                { name: "email", label: "Email", help: "With Auth.Oidc_bind_by_email, an account with only an email takes its SSO subject at first sign-in." },
                { name: "password", label: "Temporary password (users)", kind: "password" },
              ]}
            />
            <FormAction
              label="Change role"
              title="Change a role"
              effect="Takes effect at the account's next request."
              endpoint="/accounts/role"
              askReason={false}
              describe={done("Role changed.")}
              fields={[
                { name: "name", label: "Account", kind: "select", options: names, required: true },
                { name: "role", label: "New role", kind: "select", options: ROLES, required: true },
              ]}
            />
            <FormAction
              label="Reset password"
              title="Reset a password"
              effect="Sets a temporary password; the person must change it at the next sign-in."
              endpoint="/accounts/password"
              askReason={false}
              describe={done("Password reset.")}
              fields={[
                { name: "name", label: "Account", kind: "select", options: accounts.filter((a) => a.kind === "USER").map((a) => a.name), required: true },
                { name: "password", label: "Temporary password", kind: "password", required: true },
              ]}
            />
          </div>
        </CardHeader>
        <DataTable
          find
          label="Accounts"
          data={accounts}
          empty={list.isSuccess ? <EmptyState title="No accounts.">Add an account to let a person sign in or a service use tokens.</EmptyState> : undefined}
          columns={[
            columns.accessor("name", { header: "Account", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
            columns.display({ id: "person", header: "Name", cell: (c) => [c.row.original.first_name, c.row.original.last_name].filter(Boolean).join(" ") || <span className="text-muted">—</span> }),
            columns.accessor("email", { header: "Email", cell: (c) => c.getValue() ?? <span className="text-muted">—</span> }),
            columns.accessor("kind", { header: "Kind", cell: (c) => words(c.getValue()) }),
            columns.accessor("role", { header: "Role", cell: (c) => words(c.getValue()) }),
            columns.display({
              id: "state",
              header: "State",
              cell: (c) => {
                const a = c.row.original;
                return a.active_flag !== "Y" ? <StatusBadge status="DISABLED" /> : a.locked_at ? <StatusBadge status="LOCKED" /> : <StatusBadge status="ACTIVE" />;
              },
            }),
            columns.accessor("failed_signins", { header: "Failed sign-ins" }),
            columns.accessor("last_signin_at", { header: "Last sign-in", cell: (c) => <When iso={c.getValue()} empty="Never" /> }),
            columns.display({
              id: "act",
              header: "Actions",
              cell: (c) => {
                const a = c.row.original;
                if (a.name === me) return <span className="text-muted">You</span>;
                if (a.active_flag !== "Y") return null;
                // Row actions sit behind one menu, so the table keeps its width at any size; each still confirms.
                return (
                  <RowActions
                    name={a.name}
                    actions={[
                      ...(a.locked_at
                        ? [{ label: "Unlock", title: `Unlock ${a.name}`, effect: "Clears the lock and the failed sign-in count so the account can sign in again.", endpoint: "/accounts/unlock", askReason: false, body: () => ({ name: a.name }), describe: done(`${a.name} unlocked.`) }]
                        : []),
                      { label: "Disable", title: `Disable ${a.name}`, effect: "Stops this account signing in and revokes its sessions and tokens; its history stays.", endpoint: "/accounts/disable", askReason: false, body: () => ({ name: a.name }), describe: done(`${a.name} disabled.`), danger: true },
                    ]}
                  />
                );
              },
            }),
          ]}
        />
      </Card>
    </div>
  );
}
