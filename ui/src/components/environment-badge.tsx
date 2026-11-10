import { environmentLabel, isProduction, type EnvironmentInfo } from "@/lib/environment";
import { cn } from "@/lib/utils";

/** One colour rule for every place the environment appears. */
const tone = (env: EnvironmentInfo): string =>
  isProduction(env) ? "bg-[var(--env-prod)] text-[var(--env-prod-fg)]" : "bg-surface text-muted shadow-raised";

export function EnvironmentBadge({ env, className }: { env: EnvironmentInfo; className?: string }) {
  return <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide", tone(env), className)}>{environmentLabel(env)}</span>;
}

/** The full-width bar above the header says which environment this is, once; the project is in the switcher. */
export function EnvironmentStrip({ env }: { env: EnvironmentInfo }) {
  return (
    <div role="status" className={cn("flex h-7 shrink-0 items-center justify-center gap-2 px-3 text-xs font-semibold tracking-wide", tone(env))}>
      {isProduction(env) ? "PRODUCTION — changes here affect live data" : environmentLabel(env)}
    </div>
  );
}
