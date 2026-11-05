import { cn } from "@/lib/utils";

/** Page tabs driven by the address, so a tab can be linked to and survives a reload. */
export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-border">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={tab.id === value}
          aria-controls="tabpanel"
          onClick={() => onChange(tab.id)}
          className={cn(
            "-mb-px cursor-pointer border-b-2 px-3 py-2 text-sm font-medium",
            tab.id === value ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
