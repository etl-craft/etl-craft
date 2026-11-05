import type { LucideIcon } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

/** A failure or refusal, always announced to assistive technology. */
export function Notice({ children, mono, className }: { children: React.ReactNode; mono?: boolean; className?: string }) {
  return (
    <p role="alert" className={cn("m-0 rounded-md bg-bad-bg p-3 text-sm text-bad", mono && "whitespace-pre-wrap font-mono text-xs", className)}>
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
  children,
}: {
  title: React.ReactNode;
  status?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="grid min-w-0 gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="m-0 text-2xl font-semibold">{title}</h1>
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
  children,
}: {
  label: string;
  icon?: LucideIcon;
  valueClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-0.5">
      <dt className="flex items-center gap-1.5 text-xs text-muted">
        {Icon ? <Icon aria-hidden className="size-3.5" /> : null}
        {label}
      </dt>
      <dd className={cn("num m-0", valueClassName)}>{children}</dd>
    </div>
  );
}

export function FactList({ children, className }: { children: React.ReactNode; className?: string }) {
  return <dl className={cn("m-0 grid grid-cols-2 gap-x-8 gap-y-3 text-[13px] sm:grid-cols-3 lg:grid-cols-5", className)}>{children}</dl>;
}

export function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1 text-xs text-muted">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 min-w-40 rounded-md border border-border-strong bg-surface px-2 text-sm text-fg max-sm:h-11"
      >
        {children}
      </select>
    </label>
  );
}

export const inputClass = "h-9 w-full rounded-md border border-border-strong bg-surface px-2 text-sm text-fg max-sm:h-11";

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-medium">{label}</span>
      {children}
    </label>
  );
}

/** Name and value pairs such as task parameters: names muted, values in monospace and wrapped. */
export function ParamList({ entries }: { entries: [string, string][] }) {
  return (
    <dl className="m-0 grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-[minmax(10rem,16rem)_1fr]">
      {entries.map(([name, value]) => (
        <div key={name} className="contents">
          <dt className="font-mono text-xs text-muted">{name}</dt>
          <dd className="m-0 break-words font-mono text-xs">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
