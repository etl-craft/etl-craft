import * as React from "react";

/**
 * The etl-craft mark: layered chevrons under a plane, on an accent tile. The tile and glyph
 * colours come from the theme (index.css), the same pair the catalog and the favicon use.
 */
export function Logo({ className }: { className?: string }) {
  const id = React.useId();
  return (
    <svg viewBox="0 0 32 32" aria-hidden focusable="false" className={className}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" className="[stop-color:var(--mark-a)]" />
          <stop offset="1" className="[stop-color:var(--mark-b)]" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${id})`} />
      <g fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="[stroke:var(--mark-glyph)]">
        <path d="M16 5.5 L24.5 9.75 L16 14 L7.5 9.75 Z" className="[fill:var(--mark-glyph)] [fill-opacity:0.26]" />
        <path d="M16 14 V25.5" />
        <path d="M9.5 17.5 L16 21 L22.5 17.5" />
        <path d="M9.5 22 L16 25.5 L22.5 22" />
      </g>
    </svg>
  );
}
