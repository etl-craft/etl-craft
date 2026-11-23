import { Ellipsis } from "lucide-react";
import * as React from "react";
import { ActionButton } from "@/components/action-button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/dropdown";
import { cn } from "@/lib/utils";
import { unavailableAction, useActionAvailability } from "@/hooks";

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
export function RowActions({ name, actions, account, agent }: { name: string; actions: RowAction[]; account?: string; agent?: number }) {
  const [chosen, setChosen] = React.useState<number | null>(null);
  const [open, setOpen] = React.useState(false);
  const platform = useActionAvailability(undefined, undefined, actions.some((a) => !a.code));
  const selected = account ? { account_name: account } : agent === undefined ? undefined : { agent_id: agent };
  const target = useActionAvailability(undefined, undefined, !!selected && open, selected);
  const safe = actions.filter((a) => !a.danger);
  const risky = actions.filter((a) => a.danger);
  function reason(a: RowAction) {
    if (account || agent !== undefined) return unavailableAction(target, a.endpoint);
    return unavailableAction(platform, a.endpoint);
  }
  const item = (a: RowAction) => {
    const unavailable = reason(a);
    return (
      <DropdownItem key={a.label} aria-label={a.label} unavailableReason={unavailable} className={cn("grid gap-0.5", a.danger && "text-bad")} onSelect={() => setChosen(actions.indexOf(a))}>
        <span>{a.label}</span>
      </DropdownItem>
    );
  };
  return (
    <>
      <DropdownMenu onOpenChange={setOpen}>
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
        <ActionButton<{ message?: string }> key={a.label} {...a} unavailableReason={reason(a)} menu={{ open: chosen === i, setOpen: (open) => setChosen(open ? i : null) }} />
      ))}
    </>
  );
}
