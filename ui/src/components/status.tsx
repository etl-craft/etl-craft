import { CircleAlert, CircleCheck, CircleDashed, CircleMinus, CircleX, LoaderCircle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "ok" | "bad" | "run" | "warn" | "idle";

const TONE: Record<Tone, string> = {
  ok: "bg-ok-bg text-ok",
  bad: "bg-bad-bg text-bad",
  run: "bg-run-bg text-run",
  warn: "bg-warn-bg text-warn",
  idle: "bg-idle-bg text-idle",
};

interface Meta {
  label: string;
  icon: LucideIcon;
  tone: Tone;
  spin?: boolean;
}

/** Blue is running, amber only warns; every status carries its own symbol as well as colour. */
const META: Record<string, Meta> = {
  SUCCESS: { label: "Success", icon: CircleCheck, tone: "ok" },
  FAILED: { label: "Failed", icon: CircleX, tone: "bad" },
  "IN-PROGRESS": { label: "Running", icon: LoaderCircle, tone: "run", spin: true },
  RUNNING: { label: "Running", icon: LoaderCircle, tone: "run", spin: true },
  SKIPPED: { label: "Skipped", icon: CircleMinus, tone: "idle" },
  QUEUED: { label: "Queued", icon: CircleDashed, tone: "idle" },
  LOST: { label: "Lost", icon: CircleAlert, tone: "warn" },
  STOPPED: { label: "Stopped", icon: CircleMinus, tone: "warn" },
  ABORTED: { label: "Aborted", icon: CircleX, tone: "warn" },
  HELD: { label: "Held", icon: CircleAlert, tone: "warn" },
  ACTIVE: { label: "Active", icon: CircleCheck, tone: "ok" },
  DRAINING: { label: "Draining", icon: CircleAlert, tone: "warn" },
  GONE: { label: "Gone", icon: CircleMinus, tone: "idle" },
  DISABLED: { label: "Disabled", icon: CircleMinus, tone: "idle" },
  LOCKED: { label: "Locked", icon: CircleX, tone: "bad" },
  REVOKED: { label: "Revoked", icon: CircleMinus, tone: "idle" },
  ENDED: { label: "Ended", icon: CircleMinus, tone: "idle" },
};

export const statusMeta = (status: string): Meta =>
  META[status] ?? { label: status.charAt(0) + status.slice(1).toLowerCase(), icon: CircleDashed, tone: "idle" };

export function StatusBadge({ status, label: named, className }: { status: string; label?: string; className?: string }) {
  const { label: own, icon: Icon, tone, spin } = statusMeta(status);
  const label = named ?? own;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", TONE[tone], className)}>
      <Icon aria-hidden className={cn("size-3.5", spin && "animate-spin")} />
      {label}
    </span>
  );
}

/** The status as a symbol alone, for dense grids and strips; its name is the accessible label. */
export function StatusMark({ status, label, className }: { status: string; label?: string; className?: string }) {
  const { icon: Icon, label: name, spin } = statusMeta(status);
  return (
    <span role="img" aria-label={label ?? name} title={label ?? name} className={cn("grid size-6 shrink-0 place-items-center rounded-full", TONE[statusMeta(status).tone], className)}>
      <Icon aria-hidden className={cn("size-3.5", spin && "animate-spin")} />
    </span>
  );
}

export const toneClass = (status: string): string => TONE[statusMeta(status).tone];
