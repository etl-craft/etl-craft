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
        className={cn("z-50 min-w-56 rounded-md border border-border bg-surface p-1 text-sm text-fg shadow-lg", className)}
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
