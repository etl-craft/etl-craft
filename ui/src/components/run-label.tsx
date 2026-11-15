import { useId, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Link } from "react-router-dom";

/** The stored label is text beside the integer; navigation always uses the integer address. */
export function RunLabel({ id, label, to, children, compact = false, truncate = false }: { id: number | string; label?: string | null; to?: string; children?: ReactNode; compact?: boolean; truncate?: boolean }) {
  const text = label;
  const tooltip = useId();
  const [shown, setShown] = useState(false);
  return <span title={text || undefined}
    onMouseEnter={truncate ? () => setShown(true) : undefined}
    onMouseLeave={truncate ? () => setShown(false) : undefined}
    onFocus={truncate ? () => setShown(true) : undefined}
    onBlur={truncate ? () => setShown(false) : undefined}
    onKeyDown={truncate ? (event) => { if (event.key === "Escape") setShown(false); } : undefined}
    className={cn(compact ? "inline-grid w-7 min-w-0 leading-3" : truncate ? "grid min-w-0 max-w-full gap-y-0.5" : "inline-flex max-w-full flex-wrap items-baseline gap-x-2 gap-y-0.5")}>

    {to ? <Link aria-describedby={shown ? tooltip : undefined} className="num font-medium text-fg hover:text-accent hover:underline" title={text || undefined} to={to}>{children ?? `#${id}`}</Link> : <span className="num">#{id}</span>}
    {text ? <span data-run-label title={text} className={compact ? "truncate text-[9px] font-normal text-muted" : truncate ? "truncate text-xs font-normal text-muted" : "break-all text-xs font-normal text-muted"}>{text}</span> : null}
    {truncate && shown && text ? <span id={tooltip} role="tooltip" className="pointer-events-none fixed z-50 mt-8 w-max max-w-[calc(100vw-2rem)] whitespace-normal break-words rounded-sm border border-border bg-surface p-2 text-xs font-normal text-fg shadow-raised">{text}</span> : null}
  </span>;
}

/** A complete POSIX shell word, without changing the stored label. */
export const copyRunLabel = (label: string): string => "'" + label.replace(/'/g, "'\\''") + "'";
