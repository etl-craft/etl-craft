import { ChartColumn, ChevronDown, ChevronRight, Database, ListChecks, Search, Table2, TriangleAlert, Workflow } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { schemasOf, type CatalogDoc } from "@/lib/catalog";
import { catalogPath, type CatalogKind } from "@/lib/routes";
import { cn } from "@/lib/utils";

export interface Selection {
  kind?: CatalogKind;
  name?: string;
}

/** Which tree item can be reached with Tab: the one last focused, so the rest are reached with the arrow keys. */
const Roving = React.createContext<{ active: string | null; first: string | null }>({ active: null, first: null });

const row = "flex min-w-0 items-center gap-1.5 rounded-sm px-1.5 py-1 text-[13px] hover:bg-surface-2";

function useTab(key: string): 0 | -1 {
  const { active, first } = React.useContext(Roving);
  return (active ?? first) === key ? 0 : -1;
}

function Group({ id, label, icon: Icon, open, toggle, children }: { id: string; label: string; icon: typeof Database; open: boolean; toggle: (id: string) => void; children: React.ReactNode }) {
  return (
    <li role="none">
      <button type="button" role="treeitem" data-key={id} tabIndex={useTab(id)} aria-expanded={open} onClick={() => toggle(id)} className={cn(row, "w-full cursor-pointer text-left font-medium")}>
        {open ? <ChevronDown aria-hidden className="size-3.5 shrink-0" /> : <ChevronRight aria-hidden className="size-3.5 shrink-0" />}
        <Icon aria-hidden className="size-4 shrink-0 text-muted" />
        <span className="truncate">{label}</span>
      </button>
      {open ? (
        <ul role="group" className="m-0 ml-3 list-none border-l border-border pl-1.5">
          {children}
        </ul>
      ) : null}
    </li>
  );
}

function Leaf({ to, label, icon: Icon, current, title }: { to: string; label: string; icon: typeof Database; current: boolean; title?: string }) {
  return (
    <li role="none">
      <Link to={to} role="treeitem" data-key={to} tabIndex={useTab(to)} aria-current={current ? "page" : undefined} title={title ?? label} className={cn(row, current && "bg-accent/15 font-medium")}>
        <Icon aria-hidden className="size-4 shrink-0 text-muted" />
        <span className="truncate">{label}</span>
      </Link>
    </li>
  );
}

/**
 * The catalog's objects as a tree, like a data explorer's: pipelines with their tasks, and the warehouse's
 * schemas with their tables. The search box narrows it to what matches, and opens what it finds.
 */
export function CatalogTree({ code, doc, selected }: { code: string; doc: CatalogDoc; selected: Selection }) {
  const [query, setQuery] = React.useState("");
  const [opened, setOpened] = React.useState<Set<string>>(() => new Set());
  const [closed, setClosed] = React.useState<Set<string>>(() => new Set());
  const [active, setActive] = React.useState<string | null>(null);
  const needle = query.trim().toLowerCase();
  // What the selection sits in is open, so the tree always shows where the page is.
  const along = new Set(["pipelines", "warehouse"]);
  if (selected.kind === "tasks" && selected.name) along.add(`pipeline:${selected.name.split(".")[0]}`);
  if (selected.kind === "pipelines" && selected.name) along.add(`pipeline:${selected.name}`);
  if (selected.kind === "tables" && selected.name) along.add(`schema:${selected.name.split(".").slice(0, -1).join(".")}`);
  const expanded = (id: string) => Boolean(needle) || (!closed.has(id) && (opened.has(id) || along.has(id)));
  const toggle = (id: string) => {
    const without = (set: Set<string>) => new Set([...set].filter((x) => x !== id));
    if (expanded(id)) {
      setClosed((c) => new Set([...c, id]));
      setOpened(without);
    } else {
      setOpened((o) => new Set([...o, id]));
      setClosed(without);
    }
  };

  const hit = (...texts: (string | null | undefined)[]) => !needle || texts.some((t) => t?.toLowerCase().includes(needle));
  const tasksOf = (pipeline: string) => doc.tasks.filter((t) => t.pipeline === pipeline);
  const pipelines = doc.pipelines.filter((p) => hit(p.code, p.name) || tasksOf(p.code).some((t) => hit(t.code)));
  const schemas = schemasOf(doc)
    .map((g) => ({ ...g, tables: g.tables.filter((t) => hit(g.schema, t.table) || t.columns.some((c) => hit(c.name))) }))
    .filter((g) => g.tables.length);
  const found = pipelines.length + schemas.reduce((n, g) => n + g.tables.length, 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
      <label className="relative block">
        <span className="sr-only">Search the catalog</span>
        <Search aria-hidden className="pointer-events-none absolute left-2 top-2 size-4 text-muted" />
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search pipelines, tables, columns" className="h-8 w-full rounded-md border border-border-strong bg-surface pl-8 pr-2 text-[13px]" />
      </label>
      <Roving.Provider value={{ active, first: catalogPath(code, "tables") }}>
      <ul
        role="tree"
        aria-label="Catalog objects"
        className="m-0 min-h-0 flex-1 list-none overflow-auto p-0"
        onFocus={(event) => setActive((event.target as HTMLElement).dataset.key ?? null)}
        onKeyDown={(event) => {
          const item = (event.target as HTMLElement).closest<HTMLElement>("[role=treeitem]");
          if (!item) return;
          const items = [...event.currentTarget.querySelectorAll<HTMLElement>("[role=treeitem]")];
          const at = items.indexOf(item);
          const open = item.getAttribute("aria-expanded");
          const go = (target: HTMLElement | undefined) => {
            if (!target) return;
            event.preventDefault();
            target.focus();
          };
          if (event.key === "ArrowDown") go(items[at + 1]);
          else if (event.key === "ArrowUp") go(items[at - 1]);
          else if (event.key === "Home") go(items[0]);
          else if (event.key === "End") go(items[items.length - 1]);
          else if (event.key === "ArrowRight") {
            if (open === "false") {
              event.preventDefault();
              item.click();
            } else if (open === "true") go(items[at + 1]);
          } else if (event.key === "ArrowLeft") {
            if (open === "true") {
              event.preventDefault();
              item.click();
            } else {
              // The nearest group above this item that holds it.
              const parent = item.closest("ul[role=group]")?.previousElementSibling as HTMLElement | null;
              if (parent?.getAttribute("role") === "treeitem") go(parent);
            }
          }
        }}
      >
        <Leaf to={catalogPath(code, "tables")} label="All tables" icon={Table2} current={selected.kind === "tables" && !selected.name} />
        <Leaf to={catalogPath(code, "insights")} label="Insights" icon={ChartColumn} current={selected.kind === "insights"} />
        <Leaf to={catalogPath(code, "gaps")} label="Schema and lineage gaps" icon={TriangleAlert} current={selected.kind === "gaps"} />
        <Group id="pipelines" label={`Pipelines (${pipelines.length})`} icon={Workflow} open={expanded("pipelines")} toggle={toggle}>
          {pipelines.map((p) => (
            <Group key={p.code} id={`pipeline:${p.code}`} label={p.code} icon={Workflow} open={expanded(`pipeline:${p.code}`) && Boolean(tasksOf(p.code).length)} toggle={toggle}>
              <Leaf to={catalogPath(code, "pipelines", p.code)} label="Overview" icon={Workflow} current={selected.kind === "pipelines" && selected.name === p.code} />
              {tasksOf(p.code)
                .filter((t) => hit(p.code, p.name, t.code))
                .map((t) => (
                  <Leaf key={t.label} to={catalogPath(code, "tasks", t.label)} label={t.code} icon={ListChecks} current={selected.kind === "tasks" && selected.name === t.label} title={t.label} />
                ))}
            </Group>
          ))}
        </Group>
        <Group id="warehouse" label={`Warehouse (${schemas.reduce((n, g) => n + g.tables.length, 0)})`} icon={Database} open={expanded("warehouse")} toggle={toggle}>
          {schemas.map((g) => (
            <Group key={g.schema} id={`schema:${g.schema}`} label={`${g.schema} (${g.tables.length})`} icon={Database} open={expanded(`schema:${g.schema}`)} toggle={toggle}>
              {g.tables.map((t) => (
                <Leaf key={t.name} to={catalogPath(code, "tables", t.name)} label={t.table} icon={Table2} current={selected.kind === "tables" && selected.name === t.name} title={t.name} />
              ))}
            </Group>
          ))}
        </Group>
      </ul>
      </Roving.Provider>
      {needle ? (
        <p className="m-0 px-1 text-xs text-muted" role="status">
          {found ? `${found} object${found === 1 ? "" : "s"} match` : "Nothing matches."}
        </p>
      ) : null}
    </div>
  );
}
