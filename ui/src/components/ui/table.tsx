import * as React from "react";
import { cn } from "@/lib/utils";

/** Where a list ends: it asks for the next rows when scrolled to its end, so a long list scrolls, never pages. */
export interface More {
  hasMore: boolean;
  loading: boolean;
  load: () => void;
}

/**
 * The one scrolling table: a long list scrolls inside a bounded box with its header kept in view, and
 * a list that continues on the server loads the next rows when the end comes into view.
 */
export function Table({ className, more, children, ...props }: React.TableHTMLAttributes<HTMLTableElement> & { more?: More }) {
  const box = React.useRef<HTMLDivElement>(null);
  const end = React.useRef<HTMLDivElement>(null);
  const { hasMore = false, loading = false, load } = more ?? {};
  React.useEffect(() => {
    if (!hasMore || loading || !load || !end.current || typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver((seen) => seen.some((entry) => entry.isIntersecting) && load(), { root: box.current, rootMargin: "200px" });
    watch.observe(end.current);
    return () => watch.disconnect();
  }, [hasMore, loading, load, children]);
  return (
    <div ref={box} className="max-h-[min(70dvh,48rem)] w-full overflow-auto">
      <table className={cn("w-full border-collapse text-[13px]", className)} {...props}>
        {children}
      </table>
      {more ? (
        <div ref={end} className="px-3 py-2 text-xs text-muted" role="status">
          {loading ? "Loading more…" : hasMore ? "Scroll for more" : "All rows loaded"}
        </div>
      ) : null}
    </div>
  );
}
export const Th = ({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th
    className={cn("sticky top-0 z-10 border-b border-border bg-surface-2 px-2.5 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted", className)}
    {...props}
  />
);
export const Td = ({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("border-b border-border px-2.5 py-2 align-middle", className)} {...props} />
);
