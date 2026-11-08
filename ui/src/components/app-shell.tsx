import { ChevronDown, LogOut, Menu, Moon, Sun, X } from "lucide-react";
import * as React from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { Notice } from "@/components/common";
import { SearchBox } from "@/components/search-box";
import { EnvironmentBadge, EnvironmentStrip } from "@/components/environment-badge";
import { DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { Logo } from "@/components/logo";
import { LiveStatus } from "@/components/live-status";
import { SessionGuard } from "@/components/session-guard";
import { ShortcutsDialog } from "@/components/shortcuts-dialog";
import { Sidebar } from "@/components/sidebar";
import { Button } from "@/components/ui/button";
import { useActiveProject, useHealth, useIdentity } from "@/hooks";
import { signOut } from "@/lib/api";
import { rememberProject } from "@/lib/project-memory";
import { rememberVisit } from "@/lib/recent";
import { aboutPath, homePath, passwordPath, projectHomePath, settingsPath } from "@/lib/routes";
import { applyTheme, initialTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const COLLAPSE_KEY = "etl-craft-nav-collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function AppShell() {
  const { project: addressed } = useParams();
  const { code, ready } = useActiveProject();
  const location = useLocation();
  // A workspace page (a pipeline, the catalog) fills the screen and its panes scroll on their own.
  const fill = /^\/projects\/[^/]+(\/(pipelines\/[^/]+|catalog(\/.*)?))?$/.test(location.pathname);
  const navigate = useNavigate();
  const searchBox = React.useRef<HTMLInputElement>(null);
  const [shortcuts, setShortcuts] = React.useState(false);
  React.useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
      if (event.key === "?" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setShortcuts(true);
      } else if ((event.key === "/" && !typing) || (event.key === "k" && (event.ctrlKey || event.metaKey))) {
        event.preventDefault();
        searchBox.current?.focus();
      }
    };
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);
  const identity = useIdentity(code);
  const health = useHealth();
  const current = health.data?.projects.find((p) => p.project === code);
  const [chosen, setTheme] = React.useState<Theme | null>(null);
  const theme = chosen ?? initialTheme(identity.data?.settings.theme);
  const [open, setOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(() => readCollapsed());
  React.useEffect(() => applyTheme(theme), [theme]);
  const mustChange = identity.data?.must_change_password;
  React.useEffect(() => {
    if (mustChange && location.pathname !== passwordPath) navigate(passwordPath, { replace: true });
  }, [mustChange, location.pathname, navigate]);
  React.useEffect(() => {
    if (code) rememberVisit(code, location.pathname);
  }, [code, location.pathname]);
  const unavailable = Boolean(addressed) && health.isSuccess && !health.data.projects.some((p) => p.project === addressed);
  React.useEffect(() => {
    if (addressed && !unavailable && health.isSuccess) rememberProject(addressed);
  }, [addressed, unavailable, health.isSuccess]);
  const env = current ? { type: current.environment_type, name: current.environment_name } : null;
  const admin = identity.data?.role === "admin";

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2">
        Skip to content
      </a>
      <SessionGuard />
      <ShortcutsDialog open={shortcuts} onClose={() => setShortcuts(false)} />
      {env ? <EnvironmentStrip env={env} /> : null}
      <header className="z-30 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)}>
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </Button>
        <Link to={code ? projectHomePath(code) : homePath} className="flex items-center gap-2 font-semibold">
          <Logo className="size-8" />
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
                <Link to={projectHomePath(p.project)} className="justify-between gap-4">
                  <span>{p.project}</span>
                  <EnvironmentBadge env={{ type: p.environment_type, name: p.environment_name }} />
                </Link>
              </DropdownItem>
            ))}
          </DropdownContent>
        </DropdownMenu>
        {code ? <SearchBox ref={searchBox} code={code} /> : null}
        <div className="ml-auto flex items-center gap-1">
          <LiveStatus className="mr-2 hidden sm:flex" />
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
                <Link to={settingsPath}>Personal settings</Link>
              </DropdownItem>
              <DropdownItem onSelect={() => setShortcuts(true)}>Keyboard shortcuts</DropdownItem>
              <DropdownItem asChild>
                <Link to={aboutPath}>Help and About</Link>
              </DropdownItem>
              <DropdownSeparator />
              <DropdownItem onSelect={() => void signOut()}>
                <LogOut className="size-4" aria-hidden /> Sign out
              </DropdownItem>
            </DropdownContent>
          </DropdownMenu>
        </div>
      </header>
      <div className="relative flex min-h-0 flex-1">
        <aside
          className={cn(
            "z-20 shrink-0 border-r border-border bg-sidebar transition-[width] duration-150",
            open ? "absolute inset-y-0 left-0 block w-64 shadow-xl lg:static lg:shadow-none" : "hidden lg:block",
            !open && (collapsed ? "lg:w-14" : "lg:w-56"),
            open && (collapsed ? "lg:w-14" : "lg:w-56"),
          )}
          onClick={() => setOpen(false)}
        >
          <Sidebar
            code={code}
            admin={admin}
            collapsed={collapsed && !open}
            onToggle={() => {
              const next = !collapsed;
              setCollapsed(next);
              try {
                window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
              } catch {
                /* the choice lasts for this page only */
              }
            }}
          />
        </aside>
        <main id="main" data-scroll-area className={cn("min-w-0 flex-1 overflow-y-auto", fill && "lg:overflow-hidden")}>
          <div data-edge="" data-fill={fill ? "" : undefined} className={cn("w-full", fill ? "flex min-h-full flex-col lg:h-full lg:min-h-0" : "min-h-full")}>
            {unavailable && ready ? (
              <Notice>
                Project {addressed} is not available: it is disabled, or this account cannot see it. Choose another project from the menu above.
              </Notice>
            ) : (
              <Outlet />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
