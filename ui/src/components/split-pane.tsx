import * as React from "react";
import { cn } from "@/lib/utils";

const KEY = "etl-craft.split.";
const MIN = 0.2;
const MAX = 0.8;
const clamp = (ratio: number) => Math.min(MAX, Math.max(MIN, ratio));

function stored(id: string, fallback: number): number {
  try {
    const value = Number(window.localStorage.getItem(KEY + id));
    return value ? clamp(value) : fallback;
  } catch {
    return fallback; // storage can be blocked; the split then simply starts at its default
  }
}

/**
 * Two panes side by side with a divider to drag (or focus and use the arrow keys; double-click or Home resets).
 * The width is remembered in this browser. Below the `lg` breakpoint the panes stack and the divider is gone.
 */
export function SplitPane({ id, left, right, initial = 0.42, className, narrowFirst = "left", minimumLeft = 0, collapsedLeft=false }: { id: string; left: React.ReactNode; right: React.ReactNode; initial?: number; className?: string; /** Which pane comes first once they stack below `lg`. */ narrowFirst?: "left" | "right"; minimumLeft?: number; collapsedLeft?:boolean }) {
  const [ratio, setRatio] = React.useState(() => stored(id, initial));
  const frame = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);
  React.useLayoutEffect(() => {
    const element = frame.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, []);
  const minimum = width ? Math.min(MAX, Math.max(MIN, minimumLeft / width)) : MIN;
  const shown = Math.max(minimum, ratio);
  const set = (next: number) => {
    const value = Math.max(minimum, clamp(next));
    setRatio(value);
    try {
      window.localStorage.setItem(KEY + id, String(value));
    } catch {
      // a blocked store only means the width is not remembered
    }
  };
  const drag = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = frame.current?.getBoundingClientRect();
    if (!box || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
    set((event.clientX - box.left) / box.width);
  };
  const key = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowLeft") set(shown - 0.02);
    else if (event.key === "ArrowRight") set(shown + 0.02);
    else if (event.key === "Home") set(initial);
    else return;
    event.preventDefault();
  };
  return (
    <div ref={frame} style={{ "--split": collapsedLeft ? "0%" : `${shown * 100}%` } as React.CSSProperties} className={cn("grid min-h-0 gap-3 lg:grid-cols-[var(--split)_7px_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)] lg:gap-0", collapsedLeft && "!grid-cols-[minmax(0,1fr)]", className)}>
      <div data-pane className={cn("flex min-h-0 min-w-0 flex-col",collapsedLeft&&"hidden")}>{left}</div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the panes"
        aria-valuemin={Math.round(minimum * 100)}
        aria-valuemax={Math.round(MAX * 100)}
        aria-valuenow={Math.round(shown * 100)}
        tabIndex={0}
        onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
        onPointerMove={drag}
        onDoubleClick={() => set(initial)}
        onKeyDown={key}
        className={cn("group hidden cursor-col-resize touch-none items-center justify-center outline-none lg:flex",collapsedLeft&&"!hidden")}
      >
        <span className="h-full w-px bg-border-strong group-hover:w-0.5 group-hover:bg-accent group-focus-visible:bg-accent group-active:bg-accent" />
      </div>
      <div data-pane className={cn("flex min-h-0 min-w-0 flex-col", narrowFirst === "right" && "max-lg:order-first")}>{right}</div>
    </div>
  );
}
