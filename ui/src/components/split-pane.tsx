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
export function SplitPane({ id, left, right, initial = 0.42, className }: { id: string; left: React.ReactNode; right: React.ReactNode; initial?: number; className?: string }) {
  const [ratio, setRatio] = React.useState(() => stored(id, initial));
  const frame = React.useRef<HTMLDivElement>(null);
  const set = (next: number) => {
    const value = clamp(next);
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
    if (event.key === "ArrowLeft") set(ratio - 0.02);
    else if (event.key === "ArrowRight") set(ratio + 0.02);
    else if (event.key === "Home") set(initial);
    else return;
    event.preventDefault();
  };
  return (
    <div ref={frame} style={{ "--split": `${ratio * 100}%` } as React.CSSProperties} className={cn("grid min-h-0 gap-4 lg:gap-0 lg:grid-cols-[var(--split)_0.75rem_minmax(0,1fr)]", className)}>
      <div className="flex min-h-0 min-w-0 flex-col">{left}</div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the panes"
        aria-valuemin={Math.round(MIN * 100)}
        aria-valuemax={Math.round(MAX * 100)}
        aria-valuenow={Math.round(ratio * 100)}
        tabIndex={0}
        onPointerDown={(event) => event.currentTarget.setPointerCapture(event.pointerId)}
        onPointerMove={drag}
        onDoubleClick={() => set(initial)}
        onKeyDown={key}
        className="group hidden cursor-col-resize touch-none items-center justify-center outline-none lg:flex"
      >
        <span className="h-16 w-1 rounded-full bg-border-strong group-hover:bg-accent group-focus-visible:bg-accent group-active:bg-accent" />
      </div>
      <div className="flex min-h-0 min-w-0 flex-col">{right}</div>
    </div>
  );
}
