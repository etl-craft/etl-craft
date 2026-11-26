import * as React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ActionButton } from "@/components/action-button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DropdownItem } from "@/components/dropdown";
import { Button } from "@/components/ui/button";
import { failureText, useActionAvailability, type AvailabilityRead } from "@/hooks";
import { postJson, project } from "@/lib/api";

type ReparseResults = { reparses: { status: string }[] };
type Menu = { open: boolean; setOpen: (open: boolean) => void };

/** The server's reason the re-parse is unavailable; undefined when it is available. */
function useReparseReason(code: string, pipeline?: string, batched?: AvailabilityRead) {
  const single = useActionAvailability(code, pipeline, !batched);
  const capabilities = batched ?? single;
  const answer = capabilities.data?.actions.find((action) => action.action === "pipelines re-parse");
  return answer?.available ? undefined : answer?.reason ??
    (capabilities.isPending ? "Checking re-parse availability…" : capabilities.error?.message ?? "Re-parse availability is unavailable.");
}

/** The confirmation for a re-parse. With `menu`, no button is drawn; a menu item opens it. */
export function PipelineReparse({ code, pipeline, onDone, menu, batched }: { code: string; pipeline?: string; onDone: () => void; menu?: Menu; batched?: AvailabilityRead }) {
  const reason = useReparseReason(code, pipeline, batched);
  return (
    <ActionButton<ReparseResults>
      code={code}
      label={pipeline ? "Re-parse pipeline" : "Re-parse all"}
      title={pipeline ? `Re-parse ${pipeline}` : `Re-parse every pipeline in ${code}`}
      effect="Validates the current pipeline definitions and records the versions that pass."
      endpoint="/pipelines/re-parse"
      unavailableReason={reason}
      askReason={false}
      body={() => ({ pipeline_code: pipeline })}
      describe={(result) => {
        const failed = result.reparses.filter(({ status }) => status === "FAILED").length;
        return failed ? `${failed} pipeline re-parses failed. Review the re-parse findings.` : "Re-parse completed.";
      }}
      onDone={onDone}
      menu={menu}
    />
  );
}

/** The menu item that opens the re-parse confirmation; grayed out with the reason when unavailable. */
export function ReparseMenuItem({ code, pipeline, onSelect }: { code: string; pipeline?: string; onSelect: () => void }) {
  const reason = useReparseReason(code, pipeline);
  return (
    <DropdownItem unavailableReason={reason} onSelect={onSelect}>
      {pipeline ? "Re-parse pipeline" : "Re-parse all"}
    </DropdownItem>
  );
}

/**
 * Re-parse each selected pipeline with its own request, so every pipeline is authorized and
 * governed on its own and reports its own outcome, as the bulk pause does.
 */
export function BulkReparse({ code, pipelines, batched }: { code: string; pipelines: string[]; batched?: AvailabilityRead }) {
  const [open, setOpen] = React.useState(false);
  const [lines, setLines] = React.useState<string[]>([]);
  const single = useActionAvailability(code, undefined, !batched);
  const availability = batched ?? single;
  const answer = availability.data?.actions.find((action) => action.action === "pipelines re-parse");
  const unavailable = !pipelines.length
    ? "Select pipelines first."
    : answer?.available === false
      ? answer.reason ?? "Re-parse is unavailable."
      : availability.isPending
        ? "Checking re-parse availability…"
        : undefined;
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: async () => {
      const outcomes: string[] = [];
      for (const pipeline_code of pipelines) {
        try {
          const result = await postJson<ReparseResults>(`${project(code)}/pipelines/re-parse`, { pipeline_code });
          const failed = result.reparses.some(({ status }) => status === "FAILED");
          outcomes.push(`${pipeline_code}: ${failed ? "failed; review the re-parse findings" : "re-parsed"}`);
        } catch (error) {
          outcomes.push(`${pipeline_code}: ${failureText(error) ?? "not re-parsed"}`);
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
        Re-parse selected
      </Button>
      <ConfirmDialog
        open={open}
        title={`Re-parse ${pipelines.length} pipeline${pipelines.length === 1 ? "" : "s"}`}
        action="Re-parse selected"
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
