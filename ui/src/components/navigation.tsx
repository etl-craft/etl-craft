import { Link, NavLink, type LinkProps, type NavLinkProps } from "react-router-dom";

import { navigationTarget } from "@/lib/navigation";

type DocumentLink = { documentation?: boolean; newTab?: boolean };
export function AppLink({ documentation, newTab, to, children, "aria-label":label, ...props }: Omit<LinkProps,"target"|"rel"> & DocumentLink) {
  const target = navigationTarget(to, documentation || newTab);
  return <Link {...props} to={to} {...target} aria-label={label && target.target ? `${label} (opens in a new tab)` : label}>{children}{target.target ? <> <span className="sr-only">(opens in a new tab)</span></> : null}</Link>;
}
export function AppNavLink({ documentation, newTab, to, children, "aria-label":label, ...props }: Omit<NavLinkProps,"target"|"rel"> & DocumentLink) {
  const target=navigationTarget(to,documentation||newTab);
  return <NavLink {...props} to={to} {...target} aria-label={label && target.target ? `${label} (opens in a new tab)` : label}>{state=><>{typeof children==="function" ? children(state) : children}{target.target ? <> <span className="sr-only">(opens in a new tab)</span></> : null}</>}</NavLink>;
}
