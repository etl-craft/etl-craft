import { cn } from "@/lib/utils";

/**
 * The etl-craft mark: three lines converge on a hexagonal core and leave as one arrow, data from several
 * sources transformed and written. One stroke in the accent colour, no tile, so it reads at 16 px on any surface.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden focusable="false" className={cn("text-accent", className)}>
      <g fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 13 L22 26 M6 32 H21 M6 51 L22 38 M52 32 H59 M55 27 L60 32 L55 37" />
        <path d="M51.00 32.00 L45.00 42.39 L33.00 42.39 L27.00 32.00 L33.00 21.61 L45.00 21.61 Z" />
      </g>
    </svg>
  );
}
