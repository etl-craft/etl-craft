import type { To } from "react-router-dom";

/** Only documentation, external links and an explicit new-tab action leave the current tab. */
export function navigationTarget(to: To, newTab = false) {
  const href = typeof to === "string" ? to : to.pathname ?? "";
  const absolute = /^[a-z][a-z\d+.-]*:|^\/\//i.test(href);
  const external = absolute && new URL(href, window.location.href).origin !== window.location.origin;
  return newTab || external ? {target:"_blank", rel:"noopener noreferrer"} as const : {};
}

/** New-tab shortcuts share the same opener isolation as links. */
export function openNavigationTab(href: string) {
  window.open(href, "_blank", "noopener,noreferrer");
}
