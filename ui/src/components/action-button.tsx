import * as React from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useToast } from "@/components/toast";
import { Button, type ButtonProps } from "@/components/ui/button";
import { failureText, useProjectInfo, useWrite } from "@/hooks";
import { project } from "@/lib/api";

/**
 * Every write action in the interface: a button, one confirmation naming the project and its
 * environment, the request, and the server's answer (or refusal) shown verbatim.
 */
export function ActionButton<TResult>({
  code,
  canSubmit,
  label,
  title,
  effect,
  endpoint,
  body,
  describe,
  onDone,
  askReason = true,
  fields,
  icon,
  variant = "outline",
  size,
  menu,
}: {
  /** The project the action changes; absent for platform actions such as agents and accounts. */
  code?: string;
  canSubmit?: boolean;
  label: string;
  title: string;
  effect: string;
  /** The API path under the project (or under /api/v1 for a platform action), such as "/controls". */
  endpoint: string;
  body: (reason: string) => unknown;
  describe: (result: TResult) => string;
  /** Called with the server's answer once the action has succeeded, for example to reload what it changed. */
  onDone?: (result: TResult) => void;
  fields?: React.ReactNode;
  /** False for requests that take no reason. */
  askReason?: boolean;
  icon?: React.ReactNode;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  /** Set when a menu opens the confirmation: no button is drawn and the menu owns whether the dialog is open. */
  menu?: { open: boolean; setOpen: (open: boolean) => void };
}) {
  const info = useProjectInfo(code).project;
  const [own, setOwn] = React.useState(false);
  const open = menu ? menu.open : own;
  const setOpen = menu ? menu.setOpen : setOwn;
  const toast = useToast();
  const write = useWrite<TResult>((code ? project(code) : "/api/v1") + endpoint, (result) => {
    toast(describe(result));
    onDone?.(result);
    setOpen(false);
  });
  if (code && !info) return null;
  return (
    <div className="grid justify-items-end gap-2">
      {menu ? null : (
      <Button
        variant={variant}
        size={size}
        onClick={() => {
          write.reset();
          setOpen(true);
        }}
      >
        {icon}
        {label}
      </Button>
      )}
      <ConfirmDialog
        open={open}
        title={title}
        action={label}
        effect={effect}
        projectCode={code}
        env={info ? { type: info.environment_type, name: info.environment_name } : undefined}
        canSubmit={canSubmit}
        error={failureText(write.error)}
        busy={write.isPending}
        onConfirm={(reason) => write.mutate(body(reason))}
        onClose={() => setOpen(false)}
        askReason={askReason}
        governance={info?.governance}
      >
        {fields}
      </ConfirmDialog>
    </div>
  );
}
