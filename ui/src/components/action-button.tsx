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
}: {
  code: string;
  label: string;
  title: string;
  effect: string;
  /** The API path under the project, such as "/controls". */
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
}) {
  const info = useProjectInfo(code).project;
  const [open, setOpen] = React.useState(false);
  const toast = useToast();
  const write = useWrite<TResult>(project(code) + endpoint, (result) => {
    toast(describe(result));
    onDone?.(result);
    setOpen(false);
  });
  if (!info) return null;
  return (
    <div className="grid justify-items-end gap-2">
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
      <ConfirmDialog
        open={open}
        title={title}
        action={label}
        effect={effect}
        projectCode={code}
        env={{ type: info.environment_type, name: info.environment_name }}
        error={failureText(write.error)}
        busy={write.isPending}
        onConfirm={(reason) => write.mutate(body(reason))}
        onClose={() => setOpen(false)}
        askReason={askReason}
      >
        {fields}
      </ConfirmDialog>
    </div>
  );
}
