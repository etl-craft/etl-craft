import {
  Activity,
  BookOpen,
  CalendarClock,
  ChartNoAxesColumn,
  Cpu,
  House,
  ListChecks,
  PanelLeftClose,
  PanelLeftOpen,
  PauseCircle,
  ShieldCheck,
  SquareTerminal,
  Upload,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { existingPath, homePath, runsPath } from "@/lib/routes";
import { cn } from "@/lib/utils";

interface Item {
  label: string;
  icon: LucideIcon;
  /** An in-app route, or a page of the existing interface until its slice lands. */
  to?: string;
  href?: string;
}

function sections(code: string | undefined, admin: boolean): { title: string; items: Item[] }[] {
  const legacy = (name: string) => existingPath(code ?? "", name);
  return [
    {
      title: "Overview",
      items: [
        { label: "Home", icon: House, to: homePath },
        ...(code ? [{ label: "Runs", icon: ListChecks, to: runsPath(code) }] : []),
      ],
    },
    ...(code
      ? [
          {
            title: "Project",
            items: [
              { label: "Pipelines", icon: Workflow, href: legacy("pipelines") },
              { label: "Scheduled runs", icon: CalendarClock, href: legacy("scheduled") },
              { label: "Held and paused", icon: PauseCircle, href: legacy("held") },
              { label: "Uploads", icon: Upload, href: legacy("uploads") },
              { label: "Insights", icon: ChartNoAxesColumn, href: legacy("insights") },
              { label: "Catalog", icon: BookOpen, href: legacy("catalog") },
              { label: "Console", icon: SquareTerminal, href: legacy("console") },
            ],
          },
        ]
      : []),
    {
      title: "Platform",
      items: [
        { label: "System health", icon: Activity, href: "/ui/system" },
        { label: "Agents", icon: Cpu, href: "/ui/agents" },
        ...(admin ? [{ label: "Administration", icon: ShieldCheck, href: "/ui/admin" }] : []),
      ],
    },
  ];
}

const row = (collapsed: boolean, active: boolean) =>
  cn(
    "flex h-9 items-center gap-3 rounded-md text-sm",
    collapsed ? "justify-center" : "px-2.5",
    active ? "bg-sidebar-active font-medium text-accent" : "text-sidebar-fg hover:bg-sidebar-active",
  );

/** The one navigation every page shares: icons always show; labels show when expanded. */
export function Sidebar({
  code,
  admin,
  collapsed,
  onToggle,
}: {
  code?: string;
  admin: boolean;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <nav aria-label="Main" className="flex-1 overflow-y-auto p-2">
        {sections(code, admin).map((section) => (
          <div key={section.title} className="mb-3 grid gap-0.5">
            {collapsed ? (
              <div className="mx-2 mb-1 h-px bg-border" aria-hidden />
            ) : (
              <p className="px-2.5 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{section.title}</p>
            )}
            {section.items.map(({ label, icon: Icon, to, href }) => {
              const content = (
                <>
                  <Icon aria-hidden className="size-[18px] shrink-0" />
                  <span className={cn("truncate", collapsed && "sr-only")}>{label}</span>
                </>
              );
              return to ? (
                <NavLink key={label} to={to} end={to === homePath} title={collapsed ? label : undefined} className={({ isActive }) => row(collapsed, isActive)}>
                  {content}
                </NavLink>
              ) : (
                <a key={label} href={href} title={collapsed ? label : undefined} className={row(collapsed, false)}>
                  {content}
                </a>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand the navigation" : "Collapse the navigation"}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand" : "Collapse"}
          className={cn(row(collapsed, false), "hidden w-full cursor-pointer lg:flex")}
        >
          {collapsed ? <PanelLeftOpen aria-hidden className="size-[18px]" /> : <PanelLeftClose aria-hidden className="size-[18px]" />}
          <span className={cn(collapsed && "sr-only")}>Collapse</span>
        </button>
      </div>
    </div>
  );
}
