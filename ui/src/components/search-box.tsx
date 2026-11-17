import { searchDetail } from "@/lib/labels";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useNavigate } from "react-router-dom";
import { failureText } from "@/hooks";
import { Button } from "@/components/ui/button";
import { Highlight, Notice } from "@/components/common";
import { hitLink } from "@/pages/search";
import { getJson, project } from "@/lib/api";
import { agentsPath, catalogPath, consolePath, pausedPath, maintenancePath, pipelinesPath, projectHomePath, runsPath, scheduledPath, searchPath, settingsPath, systemPath, uploadsPath } from "@/lib/routes";
import type { SearchView } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUPS: [string, string][] = [
  ["PIPELINE", "Pipelines"],
  ["TASK", "Tasks"],
  ["TABLE", "Tables"],
  ["RUN", "Runs"],
];
const PER_GROUP = 4;

/** Pages reachable by name from the search box, like a command palette's navigation entries. */
const pagesOf = (code: string): { label: string; to: string }[] => [
  { label: "Home", to: projectHomePath(code) },
  { label: "Pipelines", to: pipelinesPath(code) },
  { label: "Catalog", to: catalogPath(code) },
  { label: "Runs", to: runsPath(code) },
  { label: "Scheduled runs", to: scheduledPath(code) },
  { label: "Paused", to: pausedPath(code) },
  { label: "Uploads", to: uploadsPath(code) },
  { label: "Console", to: consolePath(code) },
  { label: "Maintenance", to: maintenancePath(code) },
  { label: "System health", to: systemPath },
  { label: "Agents", to: agentsPath },
  { label: "Settings", to: settingsPath },
];

/** The top-bar search: matches appear grouped as you type, arrow keys pick one, Enter opens it, and Enter with none picked lists every result. */
export const SearchBox = React.forwardRef<HTMLInputElement, { code: string }>(function SearchBox({ code }, ref) {
  const navigate = useNavigate();
  const [text, setText] = React.useState("");
  const [typed, setTyped] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [at, setAt] = React.useState(-1);
  const root = React.useRef<HTMLDivElement>(null);
  const listId = React.useId();
  const optionId = (index: number) => `${listId}-option-${index}`;
  // The question is sent a moment after typing stops.
  React.useEffect(() => {
    const wait = window.setTimeout(() => setTyped(text.trim()), 200);
    return () => window.clearTimeout(wait);
  }, [text]);
  const found = useQuery({ queryKey: ["suggest", code, typed], queryFn: () => getJson<SearchView>(`${project(code)}/search`, { q: typed }), enabled: typed.length >= 2, staleTime: 15_000 });
  // Matches for an earlier question are never offered: Enter would open a result for text no longer in the box.
  const current = typed === text.trim();
  const groups = (typed.length < 2 || !current ? [] : GROUPS).map(([kind, label]) => ({ label, hits: (found.data?.hits ?? []).filter((h) => h.kind === kind).slice(0, PER_GROUP) })).filter((g) => g.hits.length);
  const pages = pagesOf(code).filter((p) => text.trim() === "" || p.label.toLowerCase().includes(text.trim().toLowerCase())).slice(0, text.trim() === "" ? 12 : 4);
  const flat: { key: string; label: string; detail: string; to: string }[] = [
    ...pages.map((p) => ({ key: `page:${p.label}`, label: p.label, detail: "Go to", to: p.to })),
    ...groups.flatMap((g) => g.hits).map((h) => ({ key: `${h.kind}:${h.label}:${h.run_id ?? ""}:${h.pipeline_code ?? ""}`, label: h.label, detail: searchDetail(h), to: hitLink(code, h).to })),
  ];
  const activeId = open && flat[at] ? optionId(at) : undefined;
  React.useEffect(() => {
    if (activeId) document.getElementById(activeId)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeId]);
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
    if (event.key === "ArrowDown" && flat.length) {
      event.preventDefault();
      setOpen(true);
      setAt((i) => (i + 1) % flat.length);
    } else if (event.key === "ArrowUp" && flat.length) {
      event.preventDefault();
      setOpen(true);
      setAt((i) => (i <= 0 ? flat.length - 1 : i - 1));
    }
  };
  let index = -1;
  return (
    <div ref={root} onKeyDown={(event) => { if (event.key === "Escape") { root.current?.querySelector("input")?.focus(); setOpen(false); } }} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} className="relative ml-2 hidden max-w-sm flex-1 sm:block">
      <form
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          const hit = flat[at];
          if (hit) go(hit.to);
          else if (text.trim()) go(searchPath(code, text.trim()));
        }}
      >
        <input
          ref={ref}
          name="q"
          type="search"
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          aria-label="Search pipelines, tasks, tables and runs"
          placeholder="Search or jump to (Ctrl+K)"
          autoComplete="off"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
            setAt(-1);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={key}
          className="h-control w-full rounded-md border border-border-strong bg-surface px-3 text-[13px]"
        />
      </form>
      {open ? (
        <div className="absolute left-0 top-full z-40 mt-1 max-h-[70vh] w-[min(34rem,90vw)] overflow-auto rounded-md border border-border bg-surface p-1 shadow-lg">
          {typed.length >= 2 && found.isError ? <div className="grid gap-2 p-2"><Notice className="min-w-0 break-words">Search for “{typed}” failed: {failureText(found.error)} Retry the search.</Notice><Button type="button" onClick={() => { root.current?.querySelector("input")?.focus(); void found.refetch(); }}>Retry search</Button></div> : null}
          <div id={listId} role="listbox" aria-label="Matches">
          {typed.length >= 2 && (found.isPending || !current) ? <p className="m-0 px-3 py-2 text-xs text-muted">Searching…</p> : null}
          {typed.length >= 2 && current && found.isSuccess && flat.length === 0 ? <p className="m-0 px-3 py-2 text-sm text-muted">Nothing matches &ldquo;{typed}&rdquo;.</p> : null}
          {pages.length ? (
            <div role="group" aria-label="Go to">
              <p className="m-0 px-3 pb-0.5 pt-2 text-xs font-semibold text-muted">Go to</p>
              {pages.map((p) => {
                index += 1;
                const mine = index;
                return (
                  <button key={p.label} id={optionId(mine)} tabIndex={-1} type="button" role="option" aria-selected={at === mine} onMouseMove={() => setAt(mine)} onClick={() => go(p.to)} className={cn("flex w-full cursor-pointer items-baseline gap-2 rounded-sm px-3 py-1 text-left text-sm", at === mine && "bg-fg/10")}>
                    <span className="truncate font-medium">{p.label}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
          {groups.map((g) => (
            <div key={g.label} role="group" aria-label={g.label}>
              <p className="m-0 px-3 pb-0.5 pt-2 text-xs font-semibold text-muted">{g.label}</p>
              {g.hits.map((h) => {
                index += 1;
                const mine = index;
                return (
                  <button key={`${h.kind}:${h.label}:${h.run_id ?? ""}:${h.pipeline_code ?? ""}`} id={optionId(mine)} tabIndex={-1} type="button" role="option" aria-selected={at === mine} onMouseMove={() => setAt(mine)} onClick={() => go(hitLink(code, h).to)} className={cn("flex w-full cursor-pointer items-baseline gap-2 rounded-sm px-3 py-1.5 text-left text-sm", at === mine && "bg-fg/10")}>
                    <span className="truncate font-medium"><Highlight text={h.label} words={typed} /></span>
                    <span className="truncate text-xs text-muted">{searchDetail(h)}</span>
                  </button>
                );
              })}
            </div>
          ))}
          </div>
          {found.isSuccess && found.data.truncated ? <p className="m-0 px-3 py-1 text-xs text-muted">Press Enter for the full list.</p> : null}
        </div>
      ) : null}
    </div>
  );
});
