import { ChevronDown } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";

/** The checklist shows this many items at a time; typing in the search box narrows it. */
const LISTED = 300;

/**
 * A spreadsheet-style column filter: a button opens a search box over a checklist with
 * "Select all". Nothing ticked means no filter. One control however many items exist.
 */
export function ChecklistFilter({ label, noun, one, known, selected, onChange, name = (item) => item }: {
  /** `noun` names the items in the plural, `one` in the singular; `name` is what is shown and searched. */
  label: string; noun: string; one: string; known: string[]; selected: string[];
  onChange: (next: string[]) => void; name?: (item: string) => string;
}) {
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
  const needle = query.trim().toLowerCase();
  const matches = known.filter((item) => name(item).toLowerCase().includes(needle));
  const toggle = (item: string) => onChange(selected.includes(item) ? selected.filter((value) => value !== item) : [...selected, item]);
  const allShown = matches.length > 0 && matches.every((item) => selected.includes(item));
  return (
    <div ref={root} className="relative" role="group" aria-label={`Filter by ${noun}`}>
      <Button size="sm" variant="outline" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)}>
        {label}{selected.length ? ` (${selected.length} selected)` : ""}
        <ChevronDown aria-hidden className="size-4" />
      </Button>
      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1 grid w-72 max-w-[85vw] gap-2 rounded-md border border-border bg-surface p-2 shadow-lg">
          <input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)} aria-label={`Search ${noun}`} placeholder={`Search ${known.length} ${noun}`} className="h-control rounded-md border border-border-strong bg-surface px-2 text-sm" />
          <label className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 text-sm font-medium hover:bg-surface-2">
            <input type="checkbox" checked={allShown} disabled={matches.length === 0}
              onChange={() => onChange(allShown ? selected.filter((item) => !matches.includes(item)) : [...new Set([...selected, ...matches])])}
              className="size-4 accent-[var(--accent)]" />
            {needle ? "Select all matches" : "Select all"}
          </label>
          <ul className="m-0 grid max-h-64 list-none gap-0.5 overflow-auto p-0">
            {matches.slice(0, LISTED).map((item) => (
              <li key={item}>
                <label className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 text-sm hover:bg-surface-2">
                  <input type="checkbox" checked={selected.includes(item)} onChange={() => toggle(item)} className="size-4 accent-[var(--accent)]" />
                  <span className="truncate">{name(item)}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between gap-2 text-xs text-muted">
            <span role="status">{matches.length === 0 ? `No ${one} matches.` : matches.length > LISTED ? `${LISTED} of ${matches.length} shown; type to narrow.` : `${matches.length} ${matches.length === 1 ? one : noun}`}</span>
            <Button size="sm" variant="ghost" disabled={selected.length === 0} onClick={() => onChange([])}>
              Clear
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Pipeline tags as a checklist filter; a pipeline, or the runs of one, must carry every tag ticked. */
export function TagFilter({ known, selected, onToggle, onClear }: { known: string[]; selected: string[]; onToggle: (tag: string) => void; onClear: () => void }) {
  if (known.length === 0) return <span className="text-xs text-muted">No pipeline has tags; declare them in PIPELINE_PARAMETERS.TAGS.</span>;
  return <ChecklistFilter label="Tags" noun="tags" one="tag" known={known} selected={selected} onChange={(next) => {
    if (next.length === 0) return onClear();
    for (const tag of new Set([...next, ...selected])) if (next.includes(tag) !== selected.includes(tag)) onToggle(tag);
  }} />;
}
