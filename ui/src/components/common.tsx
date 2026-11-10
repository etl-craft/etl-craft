import { DropdownSelect } from "@/components/dropdown";
import { ArrowLeft, Inbox, type LucideIcon } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

/** The path to the page from the project's lists, each part a link except the last. */
export function Breadcrumbs({ trail }: { trail: { label: string; to?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-xs text-muted">
      {trail.map((part, i) => (
        <React.Fragment key={`${i}:${part.label}`}>
          {i > 0 ? <span aria-hidden>/</span> : null}
          {part.to ? (
            <Link to={part.to} className="hover:text-fg hover:underline">
              {part.label}
            </Link>
          ) : (
            <span aria-current="page" className="text-fg">
              {part.label}
            </span>
          )}
        </React.Fragment>
      ))}
    </nav>
  );
}

/** Text with every occurrence of the search words marked, so a result shows why it matched. */
export function Highlight({ text, words }: { text: string; words: string }) {
  const needle = words.trim();
  if (!needle) return <>{text}</>;
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "i"));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === needle.toLowerCase() ? (
          <mark key={i} className="rounded-xs bg-warn-bg px-0.5 text-inherit">
            {part}
          </mark>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        ),
      )}
    </>
  );
}

/** Previous and next for a list shown a page at a time: "26 to 50 of 130". */
export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (total <= size) return null;
  const from = (page - 1) * size + 1;
  return (
    <nav aria-label="Pages" className="flex items-center justify-end gap-3 border-t border-border px-3 py-1.5 text-xs text-muted">
      <span className="num">
        {from} to {Math.min(total, page * size)} of {total}
      </span>
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className="cursor-pointer rounded-sm border border-border-strong px-2 py-0.5 enabled:hover:bg-surface-2 disabled:opacity-40">
        Previous
      </button>
      <button type="button" disabled={page >= pages} onClick={() => onPage(page + 1)} className="cursor-pointer rounded-sm border border-border-strong px-2 py-0.5 enabled:hover:bg-surface-2 disabled:opacity-40">
        Next
      </button>
    </nav>
  );
}

/** One setting as a row: what it is and why on the left, its control on the right, a divider below. */
export function SettingRow({ title, hint, children }: { title: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 border-b border-border px-4 py-3 md:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] md:gap-8">
      <div className="grid content-start gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        {hint ? <span className="text-xs text-muted">{hint}</span> : null}
      </div>
      <div className="min-w-0 max-w-md">{children}</div>
    </div>
  );
}

/** A failure or refusal, always announced to assistive technology. */
export function Notice({ children, mono, info, className }: { children: React.ReactNode; mono?: boolean; info?: boolean; className?: string }) {
  return (
    <p
      role={info ? "status" : "alert"}
      className={cn("m-0 rounded-md p-3 text-sm", info ? "bg-idle-bg text-fg" : "bg-bad-bg text-bad", mono && "whitespace-pre-wrap font-mono text-xs", className)}
    >
      {children}
    </p>
  );
}

/** A list with nothing in it: a symbol, what is missing, and the step that fills it. */
export function EmptyState({ title, children, className }: { title: React.ReactNode; children?: React.ReactNode; className?: string }) {
  return (
    <div role="status" className={cn("grid justify-items-center gap-1.5 px-4 py-10 text-center", className)}>
      <Inbox aria-hidden className="mb-1 size-6 text-muted" strokeWidth={1.5} />
      <p className="m-0 text-sm font-medium text-fg">{title}</p>
      {children ? <p className="m-0 max-w-md text-[13px] text-muted">{children}</p> : null}
    </div>
  );
}

export function Loading({ what, className }: { what: string; className?: string }) {
  return (
    <p role="status" className={cn("m-0 text-muted", className)}>
      Loading {what}…
    </p>
  );
}

export function Eyebrow({ children, className }: { children: React.ReactNode; className?: string }) {
  return <p className={cn("m-0 text-xs font-semibold uppercase tracking-wide text-muted", className)}>{children}</p>;
}

/** A page's title row: title, optional status and subtitle, actions on the right, details below. */
export function PageHeader({
  title,
  status,
  subtitle,
  actions,
  compact,
  back,
  children,
}: {
  title: React.ReactNode;
  status?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  /** A smaller title and tighter spacing, for a page whose body is the point (a run). */
  compact?: boolean;
  /** The page this one is nested under, such as the list it is one row of; a page reached from the navigation has none, so no arrow. */
  back?: { to: string; label: string } | null;
  children?: React.ReactNode;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-y-2", compact ? "gap-x-3" : "gap-x-4")}>
      <div className={cn("grid min-w-0 flex-1", compact ? "gap-1" : "gap-2")}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {back ? (
            <Link to={back.to} aria-label={`Back to ${back.label}`} title={`Back to ${back.label}`} className="-ml-1 grid size-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-fg">
              <ArrowLeft className="size-4" aria-hidden />
            </Link>
          ) : null}
          <h1 className={cn("m-0 font-semibold tracking-tight", compact ? "text-lg" : "text-2xl leading-8")}>{title}</h1>
          {status}
        </div>
        {subtitle ? <p className="m-0 text-sm text-muted">{subtitle}</p> : null}
        {children}
      </div>
      {actions ? <div className="shrink-0 max-sm:w-full">{actions}</div> : null}
    </header>
  );
}

export function Fact({
  label,
  icon: Icon,
  valueClassName,
  inline,
  children,
}: {
  label: string;
  icon?: LucideIcon;
  valueClassName?: string;
  /** Label and value on one line, as in a FactList that is `inline`. */
  inline?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={inline ? "flex items-baseline gap-1.5" : "grid gap-0.5"}>
      <dt className="flex items-center gap-1.5 text-xs text-muted">
        {Icon ? <Icon aria-hidden className="size-3.5" /> : null}
        {label}
      </dt>
      <dd className={cn("num m-0", inline && "min-w-0 truncate", valueClassName)}>{children}</dd>
    </div>
  );
}

/** Facts in a grid; `inline` makes one wrapping line of "label value" pairs, for a compact header. */
export function FactList({ children, className, inline }: { children: React.ReactNode; className?: string; inline?: boolean }) {
  return (
    <dl className={cn("m-0 text-[13px]", inline ? "flex flex-wrap items-baseline gap-x-6 gap-y-1" : "grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3 lg:grid-cols-5", className)}>
      {children}
    </dl>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  compact,
  hideLabel,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  compact?: boolean;
  /** The label stays for assistive technology; a row around the control already names it. */
  hideLabel?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Field label={label} compact={compact} hideLabel={hideLabel}>
      <DropdownSelect value={value} onChange={(event) => onChange(event.target.value)} className={cn(inputClass, "min-w-40")}>
        {children}
      </DropdownSelect>
    </Field>
  );
}

export const inputClass = "h-8 w-full rounded-md border border-border-strong bg-surface px-2.5 text-[13px] text-fg max-sm:h-11";

/** A labelled control: one style for every form; `compact` is the small muted label used above toolbar filters. */
export function Field({ label, compact, hideLabel, children }: { label: string; compact?: boolean; hideLabel?: boolean; children: React.ReactNode }) {
  return (
    // A toolbar filter keeps the width of its control; a form field fills its column.
    <label className={cn("grid gap-1", compact ? "w-fit justify-self-start text-xs text-muted" : "text-sm")}>
      <span className={hideLabel ? "sr-only" : compact ? undefined : "font-medium"}>{label}</span>
      {children}
    </label>
  );
}

/** Name and value pairs such as task parameters: names muted, values in monospace and wrapped. */
export function ParamList({ entries }: { entries: [string, string][] }) {
  return (
    <dl className="m-0 grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-[max-content_1fr]">
      {entries.map(([name, value]) => (
        <div key={name} className="contents">
          <dt className="font-mono text-xs text-muted">{name}</dt>
          <dd className="m-0 break-words font-mono text-xs">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A headline number with its label, for summary rows. */
export function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  // A number is the headline; "Not measured" and its kind are said quietly.
  const absent = typeof value === "string" && /^(Not measured|None|No finished runs)$/.test(value);
  return (
    <Fact label={label} valueClassName={absent ? "text-base text-muted" : cn("text-2xl font-semibold", tone)}>
      {value}
    </Fact>
  );
}
