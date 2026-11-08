import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useNavigate } from "react-router-dom";
import { hitLink } from "@/pages/search";
import { getJson, project } from "@/lib/api";
import { searchPath } from "@/lib/routes";
import type { SearchHit, SearchView } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUPS: [string, string][] = [
  ["PIPELINE", "Pipelines"],
  ["TASK", "Tasks"],
  ["TABLE", "Tables"],
  ["RUN", "Runs"],
];
const PER_GROUP = 4;

/** The top-bar search: matches appear grouped as you type, arrow keys pick one, Enter opens it, and Enter with none picked lists every result. */
export const SearchBox = React.forwardRef<HTMLInputElement, { code: string }>(function SearchBox({ code }, ref) {
  const navigate = useNavigate();
  const [text, setText] = React.useState("");
  const [typed, setTyped] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [at, setAt] = React.useState(-1);
  const root = React.useRef<HTMLDivElement>(null);
  // The question is sent a moment after typing stops.
  React.useEffect(() => {
    const wait = window.setTimeout(() => setTyped(text.trim()), 200);
    return () => window.clearTimeout(wait);
  }, [text]);
  const found = useQuery({ queryKey: ["suggest", code, typed], queryFn: () => getJson<SearchView>(`${project(code)}/search`, { q: typed }), enabled: typed.length >= 2, staleTime: 15_000 });
  const groups = GROUPS.map(([kind, label]) => ({ label, hits: (found.data?.hits ?? []).filter((h) => h.kind === kind).slice(0, PER_GROUP) })).filter((g) => g.hits.length);
  const flat: SearchHit[] = groups.flatMap((g) => g.hits);
  React.useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => (root.current?.contains(event.target as Node) ? undefined : setOpen(false));
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const go = (to: string) => {
    setOpen(false);
    setText("");
    navigate(to);
  };
  const key = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") setOpen(false);
    else if (event.key === "ArrowDown" && flat.length) {
      event.preventDefault();
      setOpen(true);
      setAt((i) => (i + 1) % flat.length);
    } else if (event.key === "ArrowUp" && flat.length) {
      event.preventDefault();
      setAt((i) => (i <= 0 ? flat.length - 1 : i - 1));
    }
  };
  let index = -1;
  return (
    <div ref={root} className="relative ml-2 hidden max-w-sm flex-1 sm:block">
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          const hit = flat[at];
          if (hit) go(hitLink(code, hit).to);
          else if (text.trim()) go(searchPath(code, text.trim()));
        }}
      >
        <input
          ref={ref}
          name="q"
          type="search"
          role="combobox"
          aria-expanded={open && typed.length >= 2}
          aria-controls="search-suggestions"
          aria-autocomplete="list"
          aria-label="Search pipelines, tasks, tables and runs"
          placeholder="Search (press /)"
          autoComplete="off"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
            setAt(-1);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={key}
          className="h-9 w-full rounded-md border border-border-strong bg-surface px-3 text-sm"
        />
      </form>
      {open && typed.length >= 2 ? (
        <div id="search-suggestions" role="listbox" aria-label="Matches" className="absolute left-0 top-full z-40 mt-1 max-h-[70vh] w-[min(34rem,90vw)] overflow-auto rounded-md border border-border bg-surface p-1 shadow-lg">
          {found.isPending ? <p className="m-0 px-3 py-2 text-xs text-muted">Searching…</p> : null}
          {found.isSuccess && flat.length === 0 ? <p className="m-0 px-3 py-2 text-sm text-muted">Nothing matches &ldquo;{typed}&rdquo;.</p> : null}
          {groups.map((g) => (
            <div key={g.label} role="group" aria-label={g.label}>
              <p className="m-0 px-3 pb-0.5 pt-2 text-xs font-semibold text-muted">{g.label}</p>
              {g.hits.map((h) => {
                index += 1;
                const mine = index;
                return (
                  <button key={`${h.kind}:${h.label}:${h.run_id ?? ""}:${h.pipeline_code ?? ""}`} type="button" role="option" aria-selected={at === mine} onMouseEnter={() => setAt(mine)} onClick={() => go(hitLink(code, h).to)} className={cn("flex w-full cursor-pointer items-baseline gap-2 rounded-sm px-3 py-1.5 text-left text-sm", at === mine && "bg-accent/15")}>
                    <span className="truncate font-medium">{h.label}</span>
                    <span className="truncate text-xs text-muted">{h.detail}</span>
                  </button>
                );
              })}
            </div>
          ))}
          {found.isSuccess && found.data.truncated ? <p className="m-0 px-3 py-1 text-xs text-muted">Press Enter for the full list.</p> : null}
        </div>
      ) : null}
    </div>
  );
});
