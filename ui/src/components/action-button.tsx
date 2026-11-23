import * as React from "react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useToast } from "@/components/toast";
import { Button, type ButtonProps } from "@/components/ui/button";
import { failureText, unavailableAction, useActionAvailability, useProjectInfo, useWrite, type AvailabilityTarget } from "@/hooks";
import { ApiError, project } from "@/lib/api";

/**
 * Every write action in the interface: a button, one confirmation naming the project and its
 * environment, the request, and the server's answer (or refusal) shown verbatim.
 */
export function ActionButton<TResult>(props: {
  /** The project the action changes; absent for platform actions such as agents and accounts. */
  code?: string;
  /** Project named in confirmation when a project-scoped body uses a platform endpoint. */
  projectCode?: string;
  canSubmit?: boolean;
  /** The server's reason this action is unavailable. */
  unavailableReason?: string | null;
  availabilityTarget?: AvailabilityTarget;
  label: string;
  title: string;
  effect: string;
  /** The API path under the project (or under /api/v1 for a platform action), such as "/controls". */
  endpoint: string;
  body: (reason: string) => unknown;
  describe: (result: TResult) => string;
  /** Called with the server's answer once the action has succeeded, for example to reload what it changed. */
  onDone?: (result: TResult) => void;
  /** Called with the failure, for example to read the targets a refusal asks to be confirmed. */
  onError?: (error: unknown) => void;
  fields?: React.ReactNode;
  /** False for requests that take no reason. */
  askReason?: boolean;
  icon?: React.ReactNode;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  /** Set when a menu opens the confirmation: no button is drawn and the menu owns whether the dialog is open. */
  menu?: { open: boolean; setOpen: (open: boolean) => void };
}) {
  const {
    code,
    projectCode,
    canSubmit,
    unavailableReason: suppliedReason,
    availabilityTarget,
    label,
    title,
    effect,
    endpoint,
    body,
    describe,
    onDone,
    onError,
    askReason = true,
    fields,
    icon,
    variant = "outline",
    size,
    menu,
  } = props;
  const needsAnswer = !Object.prototype.hasOwnProperty.call(props, "unavailableReason") && !menu;
  const [own, setOwn] = React.useState(false);
  const open = menu ? menu.open : own;
  const setOpen = menu ? menu.setOpen : setOwn;
  const projectInfo = useProjectInfo(code);
  const info = projectInfo.project;
  const input = (needsAnswer && (!fields || open) ? body("") : {}) as Record<string, unknown>;
  const name = typeof input.name === "string" && input.name.trim() ? input.name : undefined;
  const target = availabilityTarget ?? (
    endpoint.startsWith("/accounts/") && name ? { account_name: name, account_role: endpoint === "/accounts/role" && typeof input.role === "string" ? input.role : undefined }
    : endpoint.startsWith("/groups/") && name && (endpoint === "/groups/disable" || input.account) ? { group_name: name, member_name: typeof input.account === "string" && input.account.trim() ? input.account : undefined }
    : endpoint.startsWith("/roles/") && name ? { role_name: name, role_action: typeof input.action === "string" && input.action.trim() ? input.action : undefined }
    : endpoint === "/alert-channels/disable" && name && typeof input.project === "string" ? { project_code: input.project, channel_name: name }
    : endpoint === "/projects/disable" && typeof input.project === "string" ? { project_code: input.project }
    : undefined
  );
  const availability = useActionAvailability(code, typeof input.pipeline_code === "string" ? input.pipeline_code : undefined, needsAnswer, target);
  const admissionReason = needsAnswer
    ? unavailableAction(availability, endpoint)
    : suppliedReason ?? undefined;
  const unavailableReason = admissionReason ?? (code && !info
    ? projectInfo.error?.message ?? (projectInfo.isPending ? "Checking project environment…" : `Project ${code}: environment is unavailable; refresh the project information before confirming.`)
    : undefined);
  const toast = useToast();
  const write = useWrite<TResult>(
    (code ? project(code) : "/api/v1") + endpoint,
    (result) => {
      toast(describe(result));
      onDone?.(result);
      setOpen(false);
    },
    onError,
  );
  return (
    <div className="grid min-w-0 justify-items-start gap-2">
      {menu ? null : (
      <Button
        variant={variant}
        size={size}
        unavailableReason={unavailableReason}
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
        projectCode={code ?? projectCode}
        env={info ? { type: info.environment_type, name: info.environment_name } : undefined}
        canSubmit={canSubmit}
        unavailableReason={unavailableReason}
        // A 428 asks for a confirmation the caller shows itself; it is not a failure.
        error={write.error instanceof ApiError && write.error.status === 428 ? null : failureText(write.error)}
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
