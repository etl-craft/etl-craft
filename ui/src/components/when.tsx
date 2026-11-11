import * as React from "react";
import { useIdentity, useTimezone } from "@/hooks";
import { formatTime, relative } from "@/lib/format";

/** One clock for every relative time on the page, ticking every 15 seconds, so they agree and stay current. */
const listeners = new Set<() => void>();
let tick = Date.now();
let timer: number | undefined;
function subscribe(listener: () => void) {
  listeners.add(listener);
  if (timer === undefined && typeof window !== "undefined")
    timer = window.setInterval(() => {
      tick = Date.now();
      listeners.forEach((l) => l());
    }, 15_000);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer !== undefined) {
      window.clearInterval(timer);
      timer = undefined;
    }
  };
}
const useNow = () => React.useSyncExternalStore(subscribe, () => tick, () => tick);

/**
 * Every moment on a page is shown here, as the account's "Time display" setting says: relative with the exact
 * time on hover, or the exact time with the relative one on hover. Exports and logs keep exact times.
 */
export function When({ iso, now, empty = "—" }: { iso: string | null | undefined; now?: number; empty?: React.ReactNode }) {
  const tz = useTimezone();
  const ticking = useNow();
  const relativeFirst = useIdentity().data?.settings.time_display !== "absolute";
  if (!iso) return <>{empty}</>;
  const at = now ?? ticking;
  const exact = formatTime(iso, tz);
  return (
    <time dateTime={iso} title={relativeFirst ? exact : relative(iso, at)} className="num whitespace-nowrap">
      {relativeFirst ? relative(iso, at) : exact}
    </time>
  );
}
