import { Notice } from "@/components/common";
import { useAutoStarts, useProjectInfo } from "@/hooks";
import { autoStarts, describeAutoStarts } from "@/lib/auto-starts";

/** Says so when the controller's or the project's setting stops schedules or automatic restarts from starting runs. */
export function AutoStartNotice({ code, className }: { code: string; className?: string }) {
  const controller = useAutoStarts();
  const project = useProjectInfo(code).project?.allowed_auto_restarts;
  const state = autoStarts(controller, project);
  if (!state?.limited) return null;
  const where = `controller allows ${describeAutoStarts(controller)}; project ${code} allows ${describeAutoStarts(project)}`;
  return (
    <Notice info className={className}>
      {state.off
        ? `Automatic starts are off for this project (${where}). The schedules and restart conditions shown here do not start runs; only a person or a trigger task does.`
        : `Automatic starts are limited for this project (${where}). ${state.schedule ? "Schedules start runs" : "Schedules do not start runs"}; ${state.endings.length ? `a pipeline restarts only after ${state.endings.join(", ").toLowerCase()}` : "no ending restarts a pipeline"}.`}
    </Notice>
  );
}
