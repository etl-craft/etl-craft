import { ShieldAlert } from "lucide-react";
import { environmentLabel, isProduction, type EnvironmentInfo } from "@/lib/environment";
import { cn } from "@/lib/utils";

/**
 * One colour rule for every place the environment appears: production is solid red with a shield, every other
 * environment a quiet raised chip. They differ in lightness, symbol and words, not in hue alone.
 */
const tone = (env: EnvironmentInfo): string =>
  isProduction(env) ? "bg-[var(--env-prod)] text-[var(--env-prod-fg)]" : "bg-surface text-muted shadow-raised";

export function EnvironmentBadge({ env, className }: { env: EnvironmentInfo; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-wide", tone(env), className)}>
      {isProduction(env) ? <ShieldAlert aria-hidden className="size-3.5 shrink-0" /> : null}
      {environmentLabel(env)}
    </span>
  );
}

/** The full-width bar above the header says which environment this is, once; the project is in the switcher. */
export function EnvironmentStrip({ env }: { env: EnvironmentInfo }) {
  return (
    <div role="status" className={cn("flex min-h-7 shrink-0 items-center justify-center gap-2 px-3 py-1 text-center text-xs font-semibold tracking-wide", tone(env))}>
      {isProduction(env) ? <ShieldAlert aria-hidden className="size-4 shrink-0" /> : null}
      {isProduction(env) ? "PRODUCTION — changes here affect live data" : environmentLabel(env)}
    </div>
  );
}
