import { ChevronDown, ExternalLink, House, ListChecks, LogOut, Menu, Moon, Sun, X } from "lucide-react";
import * as React from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { EnvironmentBadge } from "@/components/environment-badge";
import { DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { useHealth, useIdentity } from "@/hooks";
import { signOut } from "@/lib/api";
import { isProduction } from "@/lib/environment";
import { applyTheme, initialTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const navLink = ({ isActive }: { isActive: boolean }) =>
  cn("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm", isActive ? "bg-sidebar-active text-white" : "text-sidebar-fg hover:bg-sidebar-active");

function Sidebar({ code, admin }: { code?: string; admin: boolean }) {
  const enc = code ? encodeURIComponent(code) : "";
  const legacy: [string, string][] = code
    ? [
        ["Pipelines", `/ui/projects/${enc}/pipelines`],
        ["Scheduled runs", `/ui/projects/${enc}/scheduled`],
        ["Held and paused", `/ui/projects/${enc}/held`],
        ["Uploads", `/ui/projects/${enc}/uploads`],
        ["Insights", `/ui/projects/${enc}/insights`],
        ["Catalog", `/ui/projects/${enc}/catalog`],
        ["Console", `/ui/projects/${enc}/console`],
      ]
    : [];
  const platform: [string, string][] = [["System health", "/ui/system"], ["Agents", "/ui/agents"], ...(admin ? ([["Administration", "/ui/admin"]] as [string, string][]) : [])];
  return (
    <nav aria-label="Main" className="grid content-start gap-5 p-3">
      <div className="grid gap-0.5">
        <p className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-sidebar-fg/60">Overview</p>
        <NavLink to="/" end className={navLink}>
          <House className="size-4" aria-hidden /> Home
        </NavLink>
        {code ? (
          <NavLink to={`/projects/${enc}/runs`} className={navLink}>
            <ListChecks className="size-4" aria-hidden /> Runs
          </NavLink>
        ) : null}
      </div>
      {[["Project", legacy], ["Platform", platform]].map(([title, links]) =>
        (links as [string, string][]).length ? (
          <div key={title as string} className="grid gap-0.5">
            <p className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-sidebar-fg/60">{title as string}</p>
            {(links as [string, string][]).map(([label, href]) => (
              <a key={href} href={href} className={navLink({ isActive: false })}>
                <ExternalLink className="size-3.5 opacity-60" aria-hidden /> {label}
              </a>
            ))}
          </div>
        ) : null,
      )}
    </nav>
  );
}

export function AppShell() {
  const { project: code } = useParams();
  const identity = useIdentity(code);
  const health = useHealth();
  const current = health.data?.projects.find((p) => p.project === code);
  const [chosen, setTheme] = React.useState<Theme | null>(null);
  const theme = chosen ?? initialTheme(identity.data?.settings.theme);
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => applyTheme(theme), [theme]);
  const mustChange = identity.data?.must_change_password;
  React.useEffect(() => {
    if (mustChange) window.location.assign("/ui/profile/password");
  }, [mustChange]);
  const env = current ? { type: current.environment_type, name: current.environment_name } : null;
  const admin = identity.data?.role === "admin";

  return (
    <div className="min-h-screen bg-bg">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2">
        Skip to content
      </a>
      {env ? (
        <div
          role="status"
          className={cn(
            "flex h-7 items-center justify-center gap-2 px-3 text-xs font-semibold tracking-wide",
            isProduction(env) ? "bg-[var(--env-prod)] text-[var(--env-prod-fg)]" : "bg-[var(--env-other)] text-[var(--env-other-fg)]",
          )}
        >
          {isProduction(env) ? "PRODUCTION — changes here affect live data" : `${env.type}${env.name ? " · " + env.name : ""}`}
          <span className="font-normal opacity-90">· {code}</span>
        </div>
      ) : null}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-surface px-4">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)}>
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </Button>
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <svg viewBox="0 0 32 32" className="size-6" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M8 21 L16 9 L24 21 M12 21 L16 15 L20 21" fill="none" stroke="var(--accent-fg)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="hidden sm:inline">etl-craft</span>
        </Link>
        <DropdownMenu>
          <DropdownTrigger asChild>
            <Button variant="outline" size="sm" className="max-w-[40vw] truncate" aria-label="Switch project">
              <span className="truncate">{code ?? "Select project"}</span>
              <ChevronDown className="size-3.5" aria-hidden />
            </Button>
          </DropdownTrigger>
          <DropdownContent align="start">
            <DropdownLabel>Projects</DropdownLabel>
            {(health.data?.projects ?? []).map((p) => (
              <DropdownItem key={p.project} asChild>
                <Link to={`/projects/${encodeURIComponent(p.project)}/runs`} className="justify-between gap-4">
                  <span>{p.project}</span>
                  <EnvironmentBadge env={{ type: p.environment_type, name: p.environment_name }} />
                </Link>
              </DropdownItem>
            ))}
          </DropdownContent>
        </DropdownMenu>
        {env ? <EnvironmentBadge env={env} className="hidden sm:inline-flex" /> : null}
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label={theme === "dark" ? "Use the light theme" : "Use the dark theme"} onClick={() => {
            const next: Theme = theme === "dark" ? "light" : "dark";
            applyTheme(next, true);
            setTheme(next);
          }}>
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
          <DropdownMenu>
            <DropdownTrigger asChild>
              <Button variant="ghost" size="sm" aria-label="Account menu">
                {identity.data?.name ?? "Account"}
                <ChevronDown className="size-3.5" aria-hidden />
              </Button>
            </DropdownTrigger>
            <DropdownContent>
              <DropdownLabel>
                {identity.data ? `${identity.data.name} · ${identity.data.role}` : "Signed in"}
                {identity.data?.project_permission ? ` · ${identity.data.project_permission}` : ""}
              </DropdownLabel>
              <DropdownItem asChild>
                <a href="/ui/profile/settings">Personal settings</a>
              </DropdownItem>
              <DropdownItem asChild>
                <a href="/ui/about">Help and About</a>
              </DropdownItem>
              <DropdownSeparator />
              <DropdownItem onSelect={() => void signOut()}>
                <LogOut className="size-4" aria-hidden /> Sign out
              </DropdownItem>
            </DropdownContent>
          </DropdownMenu>
        </div>
      </header>
      <div className="lg:grid lg:grid-cols-[14rem_1fr]">
        <aside
          className={cn(
            "bg-sidebar lg:sticky lg:top-[5.25rem] lg:block lg:h-[calc(100vh-5.25rem)] lg:overflow-y-auto",
            open ? "fixed inset-x-0 top-[5.25rem] z-20 block h-[calc(100vh-5.25rem)] overflow-y-auto" : "hidden",
          )}
          onClick={() => setOpen(false)}
        >
          <Sidebar code={code} admin={admin} />
        </aside>
        <main id="main" className="mx-auto w-full max-w-[1400px] min-w-0 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
