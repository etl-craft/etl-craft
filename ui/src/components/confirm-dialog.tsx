import { ShieldAlert } from "lucide-react";
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
  askReason = true,
  canSubmit = true,
  children,
}: {
  open: boolean;
  title: string;
  action: string;
  effect: string;
  /** Absent for platform actions, which belong to the whole server rather than one project. */
  projectCode?: string;
  env?: EnvironmentInfo;
  error: string | null;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onClose: () => void;
  /** False for requests that take no reason; the field is then not shown. */
  askReason?: boolean;
  /** False while the form fields in `children` are incomplete. */
  canSubmit?: boolean;
  children?: React.ReactNode;
}) {
  const [reason, setReason] = React.useState("");
  const [typed, setTyped] = React.useState("");
  const production = !!env && !!projectCode && isProduction(env);
  const ready = canSubmit && (!askReason || reason.trim().length > 0) && (!production || typed === projectCode);
  return (
    <Dialog open={open} onClose={onClose} labelledBy="confirm-title" className={production ? "border-2 border-[var(--env-prod)]" : undefined}>
      {production ? (
        // The page's own strip is behind the backdrop while this is open, so the dialog says it again.
        <p className="m-0 flex items-center gap-2 bg-[var(--env-prod)] px-5 py-2 text-sm font-bold text-[var(--env-prod-fg)]">
          <ShieldAlert aria-hidden className="size-4 shrink-0" />
          Production — this changes live data
        </p>
      ) : null}
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
            <span className="font-medium">{projectCode ?? "All projects"}</span>
            {env ? <EnvironmentBadge env={env} /> : null}
          </p>
          <p className="text-sm text-muted">{effect}</p>
        </div>
        {children}
        {askReason ? (
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
        ) : null}
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
          <Button type="submit" variant={production ? "dangerSolid" : "primary"} disabled={!ready || busy}>
            {busy ? "Working…" : action}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
