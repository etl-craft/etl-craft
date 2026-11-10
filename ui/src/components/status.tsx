import { ArrowRightLeft, Ban, Check, Circle, CircleDashed, CircleStop, Clock, ClockAlert, Hand, LoaderCircle, Lock, Minus, TimerOff, TriangleAlert, X, type LucideIcon } from "lucide-react";
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

/**
 * Every status the server sends, with its word, symbol and colour: green succeeded, red failed or timed out,
 * blue running, grey waiting, slate stopped or skipped, and amber only for retries and warnings (a lost attempt,
 * an SLA breach). The symbol and word carry the meaning; colour only repeats it.
 */
const META: Record<string, Meta> = {
  // Runs, task runs, attempts and items.
  SUCCESS: { label: "Success", icon: Check, tone: "ok" },
  FAILED: { label: "Failed", icon: X, tone: "bad" },
  TIMED_OUT: { label: "Timed out", icon: TimerOff, tone: "bad" },
  "IN-PROGRESS": { label: "Running", icon: LoaderCircle, tone: "run", spin: true },
  RUNNING: { label: "Running", icon: LoaderCircle, tone: "run", spin: true },
  CLAIMED: { label: "Claimed", icon: LoaderCircle, tone: "run", spin: true },
  QUEUED: { label: "Queued", icon: Clock, tone: "idle" },
  NOT_STARTED: { label: "Not started", icon: CircleDashed, tone: "idle" },
  SKIPPED: { label: "Skipped", icon: Minus, tone: "idle" },
  CANCELLED: { label: "Cancelled", icon: Ban, tone: "idle" },
  CANCEL_REQUESTED: { label: "Cancel requested", icon: Ban, tone: "idle" },
  HANDED_OFF: { label: "Handed off", icon: ArrowRightLeft, tone: "idle" },
  LOST: { label: "Lost", icon: TriangleAlert, tone: "warn" },
  STOPPED: { label: "Stopped", icon: CircleStop, tone: "idle" },
  ABORTED: { label: "Aborted", icon: Ban, tone: "idle" },
  HELD: { label: "Held", icon: Hand, tone: "idle" },
  // SLA of a run.
  MET: { label: "Met", icon: Check, tone: "ok" },
  BREACHED: { label: "Breached", icon: ClockAlert, tone: "warn" },
  // Uploads, seeds and file decisions.
  LOADED: { label: "Loaded", icon: Check, tone: "ok" },
  ACCEPTED: { label: "Accepted", icon: Check, tone: "ok" },
  REFUSED: { label: "Refused", icon: X, tone: "bad" },
  UNCHANGED: { label: "Unchanged", icon: Minus, tone: "idle" },
  // Protected writes.
  PENDING: { label: "Pending", icon: Clock, tone: "idle" },
  COMMITTED: { label: "Committed", icon: Check, tone: "ok" },
  ABANDONED: { label: "Abandoned", icon: Ban, tone: "idle" },
  // Agents and accounts.
  ACTIVE: { label: "Active", icon: Check, tone: "ok" },
  DRAINING: { label: "Draining", icon: TriangleAlert, tone: "warn" },
  GONE: { label: "Gone", icon: Minus, tone: "idle" },
  DISABLED: { label: "Disabled", icon: Minus, tone: "idle" },
  LOCKED: { label: "Locked", icon: Lock, tone: "bad" },
  REVOKED: { label: "Revoked", icon: Minus, tone: "idle" },
  ENDED: { label: "Ended", icon: Minus, tone: "idle" },
};

/** A status this map does not know keeps its own words, without a symbol that would claim a meaning. */
const unknown = (status: string): Meta => {
  const words = status.replace(/[_-]+/g, " ").toLowerCase();
  return { label: words.charAt(0).toUpperCase() + words.slice(1), icon: Circle, tone: "idle" };
};

export const statusMeta = (status: string): Meta => META[status] ?? unknown(status);

/** In a dense list only failures and warnings keep their tinted pill; every other state is its symbol and word. */
const QUIET: Record<Tone, string> = { ok: "text-ok", bad: TONE.bad, run: "text-run", warn: TONE.warn, idle: "text-idle" };

export function StatusBadge({ status, label: named, className, quiet }: { status: string; label?: string; className?: string; quiet?: boolean }) {
  const { label: own, icon: Icon, tone, spin } = statusMeta(status);
  const label = named ?? own;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full py-0.5 pl-1.5 pr-2 text-xs font-medium", quiet ? QUIET[tone] : TONE[tone], className)}>
      <Icon aria-hidden className={cn("size-3.5 shrink-0", spin && "animate-spin")} />
      {label}
    </span>
  );
}

/** The status as a symbol alone, for dense grids and strips; its name is the accessible label. */
export function StatusMark({ status, label, className, solid }: { status: string; label?: string; className?: string; solid?: boolean }) {
  const { icon: Icon, label: name, spin, tone } = statusMeta(status);
  return (
    <span role="img" aria-label={label ?? name} title={label ?? name} className={cn("grid size-5 shrink-0 place-items-center rounded-sm", solid ? SOLID[tone] : TONE[tone], className)}>
      <Icon aria-hidden strokeWidth={2.5} className={cn("size-3", spin && "animate-spin")} />
    </span>
  );
}

/** Solid marks keep their symbol at 3:1 or better: a dark symbol on the light fills, white on the dark ones. */
const SOLID: Record<Tone, string> = {
  ok: "bg-ok-solid text-ok-glyph",
  bad: "bg-bad-solid text-bad-glyph",
  run: "bg-run-solid text-run-glyph",
  warn: "bg-warn-solid text-warn-glyph",
  idle: "bg-idle-solid text-idle-glyph",
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

/** Whether a status is a failure (red), for summaries that count failures. */
export const isFailure = (status: string | null | undefined): boolean => !!status && statusMeta(status).tone === "bad";

/**
 * A task's state in a run, when the run has no row for it: queued while the run is still going, skipped when the
 * whole run was skipped, and otherwise not started. A finished run never shows its untouched tasks as queued.
 */
export function taskStatus(status: string | null | undefined, run?: { status: string; end_date: string | null }): string {
  if (status) return status;
  if (!run || !run.end_date) return "QUEUED";
  return run.status === "SKIPPED" ? "SKIPPED" : "NOT_STARTED";
}

/** A run's SLA verdict worth showing: a breach always, "met" only for a run that succeeded. */
export const slaVerdict = (run: { status: string; sla_status: string | null | undefined }): string | null =>
  run.sla_status === "BREACHED" || (run.sla_status && run.status === "SUCCESS") ? run.sla_status : null;
