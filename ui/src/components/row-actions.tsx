import { Ellipsis } from "lucide-react";
import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { cn } from "@/lib/utils";

export interface RowAction {
  label: string;
  title: string;
  effect: string;
  endpoint: string;
  body: (reason: string) => unknown;
  describe: (result: { message?: string }) => string;
  askReason?: boolean;
  /** A destructive action sits below a divider, in red; its confirmation still names the target. */
  danger?: boolean;
  code?: string;
}

/** A row's actions behind one menu; each opens the shared confirmation, so nothing destructive is a single click. */
export function RowActions({ name, actions }: { name: string; actions: RowAction[] }) {
  const [chosen, setChosen] = React.useState<number | null>(null);
  const safe = actions.filter((a) => !a.danger);
  const risky = actions.filter((a) => a.danger);
  const item = (a: RowAction) => (
    <DropdownItem key={a.label} className={cn(a.danger && "text-bad")} onSelect={() => setChosen(actions.indexOf(a))}>
      {a.label}
    </DropdownItem>
  );
  return (
    <>
      <DropdownMenu>
        <DropdownTrigger aria-label={`Actions for ${name}`} className="grid size-7 cursor-pointer place-items-center rounded-sm text-muted hover:bg-surface-2 hover:text-fg">
          <Ellipsis className="size-4" aria-hidden />
        </DropdownTrigger>
        <DropdownContent className="min-w-40">
          {safe.map(item)}
          {safe.length && risky.length ? <DropdownSeparator /> : null}
          {risky.map(item)}
        </DropdownContent>
      </DropdownMenu>
      {actions.map((a, i) => (
        <ActionButton<{ message?: string }> key={a.label} {...a} menu={{ open: chosen === i, setOpen: (open) => setChosen(open ? i : null) }} />
      ))}
    </>
  );
}
