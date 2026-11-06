import { focusManager } from "@tanstack/react-query";
import * as React from "react";
import { cn } from "@/lib/utils";

/** The platform dialog: it traps focus, closes on Escape and restores focus without a script. */
export function Dialog({
  open,
  onClose,
  labelledBy,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ref = React.useRef<HTMLDialogElement>(null);
  React.useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
    // Pages refresh themselves; while a dialog is open nothing may change under the person.
    focusManager.setFocused(open ? false : undefined);
    return () => focusManager.setFocused(undefined);
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={labelledBy}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      className={cn(
        "m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/50",
        className,
      )}
    >
      {open ? children : null}
    </dialog>
  );
}
