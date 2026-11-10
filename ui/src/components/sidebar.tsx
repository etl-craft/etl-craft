import {
  Activity,
  BookOpen,
  CalendarClock,
  Cpu,
  House,
  LayoutList,
  ListChecks,
  PanelLeftClose,
  PanelLeftOpen,
  PauseCircle,
  ShieldCheck,
  Wrench,
  SquareTerminal,
  Upload,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { adminPath, agentsPath, systemPath, catalogPath, consolePath, heldPath, homePath, maintenancePath, pipelinesPath, projectHomePath, projectsPath, runsPath, scheduledPath, uploadsPath } from "@/lib/routes";
import { cn } from "@/lib/utils";

interface Item {
  label: string;
  icon: LucideIcon;
  /** An in-app route, or a page of the existing interface until its slice lands. */
  to?: string;
  href?: string;
}

function sections(code: string | undefined, admin: boolean): { title: string; items: Item[] }[] {
  return [
    {
      title: "Overview",
      items: [
        { label: "Home", icon: House, to: code ? projectHomePath(code) : homePath },
        ...(code
          ? [
              { label: "Pipelines", icon: Workflow, to: pipelinesPath(code) },
              { label: "Catalog", icon: BookOpen, to: catalogPath(code) },
            ]
          : []),
      ],
    },
    ...(code
      ? [
          {
            title: "Operations",
            items: [
              { label: "Runs", icon: ListChecks, to: runsPath(code) },
              { label: "Scheduled runs", icon: CalendarClock, to: scheduledPath(code) },
              { label: "Held and paused", icon: PauseCircle, to: heldPath(code) },
              { label: "Uploads", icon: Upload, to: uploadsPath(code) },
              { label: "Console", icon: SquareTerminal, to: consolePath(code) },
              ...(admin ? [{ label: "Maintenance", icon: Wrench, to: maintenancePath(code) }] : []),
            ],
          },
        ]
      : []),
    {
      title: "Platform",
      items: [
        { label: "Projects", icon: LayoutList, to: projectsPath },
        { label: "System health", icon: Activity, to: systemPath },
        { label: "Agents", icon: Cpu, to: agentsPath },
        ...(admin ? [{ label: "Administration", icon: ShieldCheck, to: adminPath() }] : []),
      ],
    },
  ];
}

const row = (collapsed: boolean, active: boolean) =>
  cn(
    "flex h-8 items-center gap-2.5 rounded-md text-[13px]",
    collapsed ? "justify-center" : "px-2.5",
    active ? "bg-sidebar-active font-medium text-fg shadow-raised [&>svg]:text-accent" : "text-sidebar-fg hover:bg-fg/5 hover:text-fg",
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
              <p className="px-2.5 pb-1 pt-2 text-xs font-medium text-muted">{section.title}</p>
            )}
            {section.items.map(({ label, icon: Icon, to, href }) => {
              const content = (
                <>
                  <Icon aria-hidden className="size-4 shrink-0" />
                  <span className={cn("truncate", collapsed && "sr-only")}>{label}</span>
                </>
              );
              return to ? (
                <NavLink key={label} to={to} end={to === homePath || to === projectsPath || to === (code ? projectHomePath(code) : homePath)} title={collapsed ? label : undefined} className={({ isActive }) => row(collapsed, isActive)}>
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
      <div className="p-2">
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
