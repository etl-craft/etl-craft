import { CircleCheck, X } from "lucide-react";
import * as React from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
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
  fields?: React.ReactNode;
  icon?: React.ReactNode;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
}) {
  const info = useProjectInfo(code).project;
  const [open, setOpen] = React.useState(false);
  const [dismissed, setDismissed] = React.useState(false);
  const write = useWrite<TResult>(project(code) + endpoint);
  if (!info) return null;
  return (
    <div className="grid justify-items-end gap-2">
      <Button
        variant={variant}
        size={size}
        onClick={() => {
          write.reset();
          setDismissed(false);
          setOpen(true);
        }}
      >
        {icon}
        {label}
      </Button>
      {write.data !== undefined && !dismissed ? (
        <div role="status" className="fixed bottom-4 right-4 z-50 flex max-w-sm items-start gap-3 rounded-lg border border-border-strong bg-surface p-3 text-sm shadow-xl">
          <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-ok" />
          <p className="m-0 min-w-0 flex-1 break-words">{describe(write.data)}</p>
          <button type="button" aria-label="Dismiss" className="cursor-pointer rounded p-0.5 text-muted hover:text-fg" onClick={() => setDismissed(true)}>
            <X aria-hidden className="size-4" />
          </button>
        </div>
      ) : null}
      <ConfirmDialog
        open={open && write.data === undefined}
        title={title}
        action={label}
        effect={effect}
        projectCode={code}
        env={{ type: info.environment_type, name: info.environment_name }}
        error={failureText(write.error)}
        busy={write.isPending}
        onConfirm={(reason) => write.mutate(body(reason))}
        onClose={() => setOpen(false)}
      >
        {fields}
      </ConfirmDialog>
    </div>
  );
}
