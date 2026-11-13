import * as React from "react";
import { cn } from "@/lib/utils";

export interface SegmentOption {
  id: string;
  label: React.ReactNode;
  title?: string;
}

/**
 * One choice among a few, as a single control: one border, one height (the shared control height), and the
 * chosen segment marked by weight, fill and aria-pressed. Every toggle of this kind in the interface is this one.
 */
export function Segmented({ label, value, options, onSelect, className }: { label: string; value: string | null; options: SegmentOption[]; onSelect: (id: string) => void; className?: string }) {
  return (
    <div role="group" aria-label={label} data-control="" className={cn("inline-flex h-control items-stretch gap-0.5 rounded-md border border-border-strong bg-surface-2 p-0.5 text-[13px]", className)}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={value === option.id}
          title={option.title}
          onClick={() => onSelect(option.id)}
          className={cn("flex cursor-pointer items-center gap-1.5 rounded-sm px-3", value === option.id ? "bg-surface font-medium text-fg ring-1 ring-border-strong" : "text-muted hover:text-fg")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
