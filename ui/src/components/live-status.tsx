import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { cn } from "@/lib/utils";

interface Snapshot {
  live: boolean;
  lost: boolean;
  updatedAt: number;
}

/** What the page's refreshing queries last did: whether any, when they last answered, and whether one is failing. */
function read(client: ReturnType<typeof useQueryClient>): Snapshot {
  const polling = client.getQueryCache().findAll({ type: "active" }).filter((q) => q.observers.some((o) => o.options.refetchInterval));
  return {
    live: polling.length > 0,
    lost: polling.some((q) => q.state.fetchFailureCount > 0 || q.state.status === "error"),
    updatedAt: Math.max(0, ...polling.map((q) => q.state.dataUpdatedAt)),
  };
}

/** "Updated N s ago", or that updates were lost: the page refreshes itself, and says when it last did. */
export function LiveStatus({ className }: { className?: string }) {
  const client = useQueryClient();
  const [snap, setSnap] = React.useState(() => read(client));
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const update = () => setSnap(read(client));
    const stop = client.getQueryCache().subscribe(update);
    const tick = window.setInterval(() => setNow(Date.now()), 5_000);
    return () => {
      stop();
      window.clearInterval(tick);
    };
  }, [client]);
  if (!snap.live) return null;
  const seconds = Math.max(0, Math.round((now - snap.updatedAt) / 1000));
  return (
    <p role="status" className={cn("m-0 flex items-center gap-2 text-xs", snap.lost ? "text-bad" : "text-muted", className)}>
      <span aria-hidden className={cn("size-2 rounded-full", snap.lost ? "bg-bad" : "bg-ok")} />
      {snap.lost ? "Live updates lost, retrying" : `Live · updated ${seconds < 5 ? "just now" : `${seconds} s ago`}`}
    </p>
  );
}
