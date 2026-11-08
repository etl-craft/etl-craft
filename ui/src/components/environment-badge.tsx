import { environmentLabel, isProduction, type EnvironmentInfo } from "@/lib/environment";
import { cn } from "@/lib/utils";

/** One colour rule for every place the environment appears. */
const tone = (env: EnvironmentInfo): string =>
  isProduction(env) ? "bg-[var(--env-prod)] text-[var(--env-prod-fg)]" : "bg-[var(--env-other)] text-[var(--env-other-fg)]";

export function EnvironmentBadge({ env, className }: { env: EnvironmentInfo; className?: string }) {
  return <span className={cn("inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-bold tracking-wide", tone(env), className)}>{environmentLabel(env)}</span>;
}

/** The full-width bar above the header says which environment this is, once; the project is in the switcher. */
export function EnvironmentStrip({ env }: { env: EnvironmentInfo }) {
  return (
    <div role="status" className={cn("flex h-7 shrink-0 items-center justify-center gap-2 px-3 text-xs font-semibold tracking-wide", tone(env))}>
      {isProduction(env) ? "PRODUCTION — changes here affect live data" : environmentLabel(env)}
    </div>
  );
}
