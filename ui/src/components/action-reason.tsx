import { useId, useState, type FocusEvent, type KeyboardEvent, type PointerEvent, type SyntheticEvent } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";

/** Keep the description available to assistive technology even when the annotation is closed. */
export function useActionReason(reason?: string) {
  const id = useId();
  const [position, setPosition] = useState<{ left: number; top: number; above: boolean } | null>(null);
  const close = () => setPosition(null);
  const show = (event: SyntheticEvent<HTMLElement>) => {
    if (!reason) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const width = Math.min(288, window.innerWidth - 16);
    const above = window.innerHeight - rect.bottom < 144 && rect.top > 144;
    setPosition({
      left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      top: above ? rect.top - 6 : rect.bottom + 6,
      above,
    });
  };
  return {
    show,
    anchor: reason ? {
      "aria-describedby": id,
      onPointerEnter: show,
      onPointerLeave: (event: PointerEvent<HTMLElement>) => {
        if (document.activeElement !== event.currentTarget) close();
      },
      onFocus: (event: FocusEvent<HTMLElement>) => show(event),
      onBlur: close,
      onKeyDown: (event: KeyboardEvent<HTMLElement>) => { if (event.key === "Escape") close(); },
    } : {},
    annotation: reason ? createPortal(
      <span
        id={id} role="tooltip" hidden={!position}
        className="pointer-events-none fixed z-[80] w-72 max-w-[calc(100vw-1rem)] rounded-md border border-border bg-surface p-2.5 text-left text-xs font-normal leading-relaxed text-fg shadow-pop"
        style={position ? { left: position.left, top: position.top, transform: position.above ? "translateY(-100%)" : undefined } : undefined}
      >
        <span className="flex items-start gap-2">
          <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted" />
          <span className="min-w-0 [overflow-wrap:anywhere]">{reason}</span>
        </span>
      </span>,
      document.body,
    ) : null,
  };
}
