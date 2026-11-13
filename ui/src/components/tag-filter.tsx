import { ChevronDown } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";

/** The checklist shows this many tags at a time; typing in the search box narrows it. */
const LISTED = 300;

/**
 * The pipeline tags as a filter list, like a spreadsheet's: a button opens a search box over a checklist,
 * and a pipeline, or the runs of one, must carry every tag ticked. One control however many tags exist.
 */
export function TagFilter({ known, selected, onToggle, onClear }: { known: string[]; selected: string[]; onToggle: (tag: string) => void; onClear: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const root = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => (root.current?.contains(event.target as Node) ? undefined : setOpen(false));
    const escape = (event: KeyboardEvent) => (event.key === "Escape" ? setOpen(false) : undefined);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  if (known.length === 0) return <span className="text-xs text-muted">No pipeline has tags; declare them in PIPELINE_PARAMETERS.TAGS.</span>;
  const needle = query.trim().toLowerCase();
  const matches = known.filter((tag) => tag.toLowerCase().includes(needle));
  return (
    <div ref={root} className="relative" role="group" aria-label="Filter by tag">
      <Button variant="outline" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)}>
        Tags{selected.length ? ` (${selected.length} selected)` : ""}
        <ChevronDown aria-hidden className="size-4" />
      </Button>
      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1 grid w-80 max-w-[85vw] gap-2 rounded-md border border-border bg-surface p-2 shadow-lg">
          <input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search tags" placeholder={`Search ${known.length} tags`} className="h-control rounded-md border border-border-strong bg-surface px-2 text-sm" />
          <ul className="m-0 grid max-h-64 list-none gap-0.5 overflow-auto p-0">
            {matches.slice(0, LISTED).map((tag) => (
              <li key={tag}>
                <label className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 text-sm hover:bg-surface-2">
                  <input type="checkbox" checked={selected.includes(tag)} onChange={() => onToggle(tag)} className="size-4 accent-[var(--accent)]" />
                  <span className="truncate">{tag}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between gap-2 text-xs text-muted">
            <span role="status">{matches.length === 0 ? "No tag matches." : matches.length > LISTED ? `${LISTED} of ${matches.length} shown; type to narrow.` : `${matches.length} tag${matches.length === 1 ? "" : "s"}`}</span>
            <Button size="sm" variant="ghost" disabled={selected.length === 0} onClick={onClear}>
              Clear
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
