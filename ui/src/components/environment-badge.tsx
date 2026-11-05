import { environmentLabel, isProduction, type EnvironmentInfo } from "@/lib/environment";
import { cn } from "@/lib/utils";

export function EnvironmentBadge({ env, className }: { env: EnvironmentInfo; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-bold tracking-wide",
        isProduction(env) ? "bg-[var(--env-prod)] text-[var(--env-prod-fg)]" : "bg-[var(--env-other)] text-[var(--env-other-fg)]",
        className,
      )}
    >
      {environmentLabel(env)}
    </span>
  );
}
