import { Notice } from "@/components/common";
import { useAutoStarts } from "@/hooks";

const EVERYTHING = "SCHEDULE|ALWAYS";

/** Says so when the environment's craft-connector.yml stops schedules or automatic restarts from starting runs. */
export function AutoStartNotice({ className }: { className?: string }) {
  const allowed = useAutoStarts();
  if (allowed === undefined || allowed === EVERYTHING) return null;
  const setting = `Orchestration.Allowed_auto_restarts = ${allowed}`;
  return (
    <Notice info className={className}>
      {allowed === "NONE"
        ? `Automatic starts are off in this environment (${setting}). The schedules and restart conditions shown here do not start runs; only a person or a trigger task does.`
        : `Automatic starts are limited in this environment (${setting}). ${allowed.split("|").includes("SCHEDULE") ? "Schedules start runs; restarts follow only the endings it names." : "Schedules do not start runs; restarts follow only the endings it names."}`}
    </Notice>
  );
}
