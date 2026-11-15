import { cn } from "@/lib/utils";

/** Page tabs driven by the address, so a tab can be linked to and survives a reload. */
export function Tabs({ tabs, value, onChange, className }: { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void; className?: string }) {
  return (
    <div role="tablist" className={cn("flex min-w-0 max-w-full shrink-0 gap-1 overflow-x-auto overscroll-x-contain touch-pan-x border-b border-border", className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={tab.id === value}
          aria-controls="tabpanel"
          onClick={() => onChange(tab.id)}
          onFocus={(event) => event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" })}
          className={cn(
            "-mb-px shrink-0 cursor-pointer border-b-2 px-3 py-2 text-sm font-medium",
            tab.id === value ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
