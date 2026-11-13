import * as Menu from "@radix-ui/react-dropdown-menu";
import * as React from "react";
import { cn } from "@/lib/utils";

/** Non-modal: modal menus inject a style element, which the page's content policy refuses. */
export const DropdownMenu = ({ children }: { children: React.ReactNode }) => <Menu.Root modal={false}>{children}</Menu.Root>;
export const DropdownTrigger = Menu.Trigger;

export function DropdownContent({ className, ...props }: React.ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        align="end"
        sideOffset={6}
        className={cn("z-50 min-w-56 rounded-lg bg-surface p-1 text-[13px] text-fg shadow-pop", className)}
        {...props}
      />
    </Menu.Portal>
  );
}

export function DropdownItem({ className, ...props }: React.ComponentProps<typeof Menu.Item>) {
  return (
    <Menu.Item
      className={cn("flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-1.5 outline-none data-[highlighted]:bg-surface-2", className)}
      {...props}
    />
  );
}

export const DropdownLabel = ({ className, ...props }: React.ComponentProps<typeof Menu.Label>) => (
  <Menu.Label className={cn("px-2.5 py-1.5 text-xs text-muted", className)} {...props} />
);
export const DropdownSeparator = () => <Menu.Separator className="my-1 h-px bg-border" />;

/** The shared native selection control keeps platform keyboard and form behaviour. */
export function DropdownSelect({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn("h-control w-full min-w-40 rounded-md border border-border-strong bg-surface px-2.5 text-[13px] text-fg", className)} {...props} />;
}

/** All disclosures share the same semantic control and chevron styling. */
export function Disclosure(props: React.DetailsHTMLAttributes<HTMLDetailsElement>) {
  return <details {...props} />;
}

export function DisclosureSummary(props: React.HTMLAttributes<HTMLElement>) {
  return <summary {...props} />;
}
