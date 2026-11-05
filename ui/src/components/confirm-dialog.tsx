import * as React from "react";
import { Notice } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EnvironmentBadge } from "@/components/environment-badge";
import { isProduction, type EnvironmentInfo } from "@/lib/environment";

/** Every write action asks here, naming the project and its environment. */
export function ConfirmDialog({
  open,
  title,
  action,
  effect,
  projectCode,
  env,
  error,
  busy,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  action: string;
  effect: string;
  projectCode: string;
  env: EnvironmentInfo;
  error: string | null;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = React.useState("");
  const [typed, setTyped] = React.useState("");
  const production = isProduction(env);
  const ready = reason.trim().length > 0 && (!production || typed === projectCode);
  return (
    <Dialog open={open} onClose={onClose} labelledBy="confirm-title">
      <form
        className="grid gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) onConfirm(reason.trim());
        }}
      >
        <div className="grid gap-2">
          <h2 id="confirm-title" className="text-base font-semibold">
            {title}
          </h2>
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{projectCode}</span>
            <EnvironmentBadge env={env} />
          </p>
          <p className="text-sm text-muted">{effect}</p>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Reason (kept in the audit trail)</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            required
            className="rounded-md border border-border-strong bg-surface p-2 text-sm"
          />
        </label>
        {production ? (
          <label className="grid gap-1 text-sm">
            <span className="font-medium">
              This is PRODUCTION. Type <code className="font-mono">{projectCode}</code> to confirm.
            </span>
            <input
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
              className="h-9 rounded-md border border-border-strong bg-surface px-2 font-mono text-sm"
            />
          </label>
        ) : null}
        {error ? (
          <Notice>{error}</Notice>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant={production ? "danger" : "primary"} disabled={!ready || busy}>
            {busy ? "Working…" : action}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
