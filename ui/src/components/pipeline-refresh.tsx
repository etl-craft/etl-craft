import { ActionButton } from "@/components/action-button";
import { useActionAvailability } from "@/hooks";

type RefreshResults = { refreshes: { status: string }[] };

export function PipelineRefresh({ code, pipeline, onDone }: { code: string; pipeline?: string; onDone: () => void }) {
  const capabilities = useActionAvailability(code, pipeline);
  const answer = capabilities.data?.actions.find((action) => action.action === "pipelines refresh");
  const reason = answer?.available ? undefined : answer?.reason ??
    (capabilities.isPending ? "Checking refresh availability…" : capabilities.error?.message ?? "Refresh availability is unavailable.");

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
    />
  );
}
