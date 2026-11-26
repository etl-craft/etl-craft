import { ArrowLeft } from "lucide-react";
import { Link, NavLink, useLocation, useNavigate, type LinkProps, type NavLinkProps } from "react-router-dom";

import { Button } from "@/components/ui/button";

import { navigationTarget } from "@/lib/navigation";

/** Whether the browser's previous entry is a page of this app (the router numbers its entries from 0). */
function appHistory(): boolean {
  const state: unknown = window.history.state;
  return typeof state === "object" && state !== null && "idx" in state && typeof state.idx === "number" && state.idx > 0;
}

/** The one back button, in the top bar of every page: the previous page; when the app was opened here, `fallback` replaces this entry. */
export function BackButton({ fallback }: { fallback: string }) {
  const navigate = useNavigate();
  const here = useLocation().pathname;
  const history = appHistory();
  const target = history ? null : fallback !== here ? fallback : undefined;
  return (
    <Button variant="ghost" size="icon" aria-label="Back" title={target === undefined ? "Nothing to go back to" : "Back"} disabled={target === undefined}
      onClick={() => (target ? navigate(target, { replace: true }) : navigate(-1))}>
      <ArrowLeft className="size-5" aria-hidden />
    </Button>
  );
}

type DocumentLink = { documentation?: boolean; newTab?: boolean };
export function AppLink({ documentation, newTab, to, children, "aria-label":label, ...props }: Omit<LinkProps,"target"|"rel"> & DocumentLink) {
  const target = navigationTarget(to, documentation || newTab);
  return <Link {...props} to={to} {...target} aria-label={label && target.target ? `${label} (opens in a new tab)` : label}>{children}{target.target ? <> <span className="sr-only">(opens in a new tab)</span></> : null}</Link>;
}
export function AppNavLink({ documentation, newTab, to, children, "aria-label":label, ...props }: Omit<NavLinkProps,"target"|"rel"> & DocumentLink) {
  const target=navigationTarget(to,documentation||newTab);
  return <NavLink {...props} to={to} {...target} aria-label={label && target.target ? `${label} (opens in a new tab)` : label}>{state=><>{typeof children==="function" ? children(state) : children}{target.target ? <> <span className="sr-only">(opens in a new tab)</span></> : null}</>}</NavLink>;
}
