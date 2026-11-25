import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ActionButton } from "@/components/action-button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DropdownItem } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { failureText, useActionAvailability, type AvailabilityRead } from "@/hooks";
import { postJson, project } from "@/lib/api";

type RefreshResults = { refreshes: { status: string }[] };
type Menu = { open: boolean; setOpen: (open: boolean) => void };

/** The server's reason the refresh is unavailable; undefined when it is available. */
function useRefreshReason(code: string, pipeline?: string, batched?: AvailabilityRead) {
  const single = useActionAvailability(code, pipeline, !batched);
  const capabilities = batched ?? single;
  const answer = capabilities.data?.actions.find((action) => action.action === "pipelines refresh");
  return answer?.available ? undefined : answer?.reason ??
    (capabilities.isPending ? "Checking refresh availability…" : capabilities.error?.message ?? "Refresh availability is unavailable.");
}

/** The confirmation for a refresh. With `menu`, no button is drawn; a menu item opens it. */
export function PipelineRefresh({ code, pipeline, onDone, menu, batched }: { code: string; pipeline?: string; onDone: () => void; menu?: Menu; batched?: AvailabilityRead }) {
  const reason = useRefreshReason(code, pipeline, batched);
  return (
    <ActionButton<RefreshResults>
      code={code}
      label={pipeline ? "Refresh pipeline" : "Refresh all"}
      title={pipeline ? `Refresh ${pipeline}` : `Refresh every pipeline in ${code}`}
      effect="Validates the current pipeline definitions and records the versions that pass."
      endpoint="/pipelines/refresh"
      unavailableReason={reason}
      askReason={false}
      body={() => ({ pipeline_code: pipeline })}
      describe={(result) => {
        const failed = result.refreshes.filter(({ status }) => status === "FAILED").length;
        return failed ? `${failed} pipeline refreshes failed. Review the refresh findings.` : "Refresh completed.";
      }}
      onDone={onDone}
      menu={menu}
    />
  );
}

/** The menu item that opens the refresh confirmation; grayed out with the reason when unavailable. */
export function RefreshMenuItem({ code, pipeline, onSelect }: { code: string; pipeline?: string; onSelect: () => void }) {
  const reason = useRefreshReason(code, pipeline);
  return (
    <DropdownItem unavailableReason={reason} onSelect={onSelect}>
      {pipeline ? "Refresh pipeline" : "Refresh all"}
    </DropdownItem>
  );
}

/**
 * Refresh each selected pipeline with its own request, so every pipeline is authorized and
 * governed on its own and reports its own outcome, as the bulk pause does.
 */
export function BulkRefresh({ code, pipelines, batched }: { code: string; pipelines: string[]; batched?: AvailabilityRead }) {
  const [open, setOpen] = React.useState(false);
  const [lines, setLines] = React.useState<string[]>([]);
  const single = useActionAvailability(code, undefined, !batched);
  const availability = batched ?? single;
  const answer = availability.data?.actions.find((action) => action.action === "pipelines refresh");
  const unavailable = !pipelines.length
    ? "Select pipelines first."
    : answer?.available === false
      ? answer.reason ?? "Refresh is unavailable."
      : availability.isPending
        ? "Checking refresh availability…"
        : undefined;
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: async () => {
      const outcomes: string[] = [];
      for (const pipeline_code of pipelines) {
        try {
          const result = await postJson<RefreshResults>(`${project(code)}/pipelines/refresh`, { pipeline_code });
          const failed = result.refreshes.some(({ status }) => status === "FAILED");
          outcomes.push(`${pipeline_code}: ${failed ? "failed; review the refresh findings" : "refreshed"}`);
        } catch (error) {
          outcomes.push(`${pipeline_code}: ${failureText(error) ?? "not refreshed"}`);
        }
      }
      return outcomes;
    },
    onSuccess: (outcomes) => {
      setLines(outcomes);
      void queryClient.invalidateQueries();
    },
  });
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        unavailableReason={unavailable}
        onClick={() => {
          run.reset();
          setLines([]);
          setOpen(true);
        }}
      >
        Refresh selected
      </Button>
      <ConfirmDialog
        open={open}
        title={`Refresh ${pipelines.length} pipeline${pipelines.length === 1 ? "" : "s"}`}
        action="Refresh selected"
        effect={`Validates and records the current definitions of: ${pipelines.join(", ")}. Each pipeline succeeds or is refused on its own.`}
        projectCode={code}
        askReason={false}
        busy={run.isPending}
        error={failureText(run.error)}
        onConfirm={() => run.mutate()}
        onClose={() => setOpen(false)}
      >
        {lines.length ? (
          <ul className="m-0 list-none space-y-1 p-0 text-sm">
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
      </ConfirmDialog>
    </>
  );
}
