import type { ReactNode } from "react";
import { Link } from "react-router-dom";

/** The stored label is text beside the integer; navigation always uses the integer address. */
export function RunLabel({ id, label, to, children, compact = false }: { id: number | string; label?: string | null; to?: string; children?: ReactNode; compact?: boolean }) {
  const text = label;
  return <span title={text || undefined} className={compact ? "inline-grid w-7 min-w-0 leading-3" : "inline-flex max-w-full flex-wrap items-baseline gap-x-2 gap-y-0.5"}>
    {to ? <Link className="num font-medium text-fg hover:text-accent hover:underline" title={text || undefined} to={to}>{children ?? `#${id}`}</Link> : <span className="num">#{id}</span>}
    {text ? <span data-run-label className={compact ? "truncate text-[9px] font-normal text-muted" : "break-all text-xs font-normal text-muted"}>{text}</span> : null}
  </span>;
}

/** A complete POSIX shell word, without changing the stored label. */
export const copyRunLabel = (label: string): string => "'" + label.replace(/'/g, "'\\''") + "'";
