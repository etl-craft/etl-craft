import { Check, Clock, LoaderCircle, Minus, TriangleAlert, X, type LucideIcon } from "lucide-react";
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
  SUCCESS: { label: "Success", icon: Check, tone: "ok" },
  FAILED: { label: "Failed", icon: X, tone: "bad" },
  "IN-PROGRESS": { label: "Running", icon: LoaderCircle, tone: "run", spin: true },
  RUNNING: { label: "Running", icon: LoaderCircle, tone: "run", spin: true },
  SKIPPED: { label: "Skipped", icon: Minus, tone: "idle" },
  QUEUED: { label: "Queued", icon: Clock, tone: "idle" },
  LOST: { label: "Lost", icon: TriangleAlert, tone: "warn" },
  STOPPED: { label: "Stopped", icon: Minus, tone: "warn" },
  ABORTED: { label: "Aborted", icon: X, tone: "warn" },
  HELD: { label: "Held", icon: TriangleAlert, tone: "warn" },
  ACTIVE: { label: "Active", icon: Check, tone: "ok" },
  DRAINING: { label: "Draining", icon: TriangleAlert, tone: "warn" },
  GONE: { label: "Gone", icon: Minus, tone: "idle" },
  DISABLED: { label: "Disabled", icon: Minus, tone: "idle" },
  LOCKED: { label: "Locked", icon: X, tone: "bad" },
  REVOKED: { label: "Revoked", icon: Minus, tone: "idle" },
  ENDED: { label: "Ended", icon: Minus, tone: "idle" },
};

export const statusMeta = (status: string): Meta =>
  META[status] ?? { label: status.charAt(0) + status.slice(1).toLowerCase(), icon: Clock, tone: "idle" };

export function StatusBadge({ status, label: named, className }: { status: string; label?: string; className?: string }) {
  const { label: own, icon: Icon, tone, spin } = statusMeta(status);
  const label = named ?? own;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full py-0.5 pl-1.5 pr-2 text-xs font-medium", TONE[tone], className)}>
      <Icon aria-hidden className={cn("size-3.5", spin && "animate-spin")} />
      {label}
    </span>
  );
}

/** The status as a symbol alone, for dense grids and strips; its name is the accessible label. */
export function StatusMark({ status, label, className, solid }: { status: string; label?: string; className?: string; solid?: boolean }) {
  const { icon: Icon, label: name, spin } = statusMeta(status);
  return (
    <span role="img" aria-label={label ?? name} title={label ?? name} className={cn("grid size-5 shrink-0 place-items-center rounded-sm", solid ? SOLID[statusMeta(status).tone] : TONE[statusMeta(status).tone], className)}>
      <Icon aria-hidden strokeWidth={2.5} className={cn("size-3", spin && "animate-spin")} />
    </span>
  );
}

const SOLID: Record<Tone, string> = {
  ok: "bg-ok-solid text-white",
  bad: "bg-bad-solid text-white",
  run: "bg-run-solid text-white",
  warn: "bg-warn-solid text-white",
  idle: "bg-idle-solid text-white",
};

const EDGE: Record<Tone, string> = {
  ok: "border-l-ok-solid",
  bad: "border-l-bad-solid",
  run: "border-l-run-solid",
  warn: "border-l-warn-solid",
  idle: "border-l-idle-solid",
};

/** The colour of a left edge that marks a card with its status. */
export const edgeClass = (status: string): string => EDGE[statusMeta(status).tone];

/** The same mark filled solid, for grids where many marks sit edge to edge. */
export const solidClass = (status: string): string => SOLID[statusMeta(status).tone];

export const toneClass = (status: string): string => TONE[statusMeta(status).tone];
