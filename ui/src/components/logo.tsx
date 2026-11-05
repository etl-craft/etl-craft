/** The etl-craft mark: a muted plane over a stem with two chevrons in the accent colour. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false" className={className}>
      <path stroke="var(--muted)" d="M12 3 L20 7 L12 11 L4 7 Z" />
      <path stroke="var(--accent)" d="M12 11 V23" />
      <path stroke="var(--accent)" d="M6 14 L12 18 L18 14" />
      <path stroke="var(--accent)" d="M6 19 L12 23 L18 19" />
    </svg>
  );
}
