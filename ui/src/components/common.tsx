import type { LucideIcon } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

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
  children,
}: {
  title: React.ReactNode;
  status?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  /** A smaller title and tighter spacing, for a page whose body is the point (a run). */
  compact?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between", compact ? "gap-3" : "gap-4")}>
      <div className="grid min-w-0 gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className={cn("m-0 font-semibold", compact ? "text-xl" : "text-2xl")}>{title}</h1>
          {status}
        </div>
        {subtitle ? <p className="m-0 text-sm text-muted">{subtitle}</p> : null}
        {children}
      </div>
      {actions}
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
      <dd className={cn("num m-0", valueClassName)}>{children}</dd>
    </div>
  );
}

/** Facts in a grid; `inline` makes one wrapping line of "label value" pairs, for a compact header. */
export function FactList({ children, className, inline }: { children: React.ReactNode; className?: string; inline?: boolean }) {
  return (
    <dl className={cn("m-0 text-[13px]", inline ? "flex flex-wrap gap-x-6 gap-y-1" : "grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3 lg:grid-cols-5", className)}>
      {children}
    </dl>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  compact,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  compact?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Field label={label} compact={compact}>
      <select value={value} onChange={(event) => onChange(event.target.value)} className={cn(inputClass, "min-w-40")}>
        {children}
      </select>
    </Field>
  );
}

export const inputClass = "h-9 w-full rounded-md border border-border-strong bg-surface px-2 text-sm text-fg max-sm:h-11";

/** A labelled control: one style for every form; `compact` is the small muted label used above toolbar filters. */
export function Field({ label, compact, children }: { label: string; compact?: boolean; children: React.ReactNode }) {
  return (
    <label className={cn("grid gap-1", compact ? "text-xs text-muted" : "text-sm")}>
      <span className={compact ? undefined : "font-medium"}>{label}</span>
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
