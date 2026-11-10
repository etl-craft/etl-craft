/** Engine codes in the words a page shows: the code stays in the data, exports and the CLI. */

/** `EMAIL_ALERT` → "Email alert": a code nobody has given a label, in words. */
export function words(code: string | null | undefined): string {
  if (!code) return "";
  const text = code.replace(/[_-]+/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const HANDLERS: Record<string, string> = {
  PYTHON: "Python",
  SQL: "SQL",
  SQL_SCRIPT: "SQL script",
  FILE_VALIDATION: "File validation",
  ERASURE: "Erasure",
  BUSINESS_RULES: "Business rules",
  EMAIL_ALERT: "Email alert",
  EVENT_WAIT: "Event wait",
  RUN_PIPELINE: "Run pipeline",
};

/** What runs a task, as a person names it. */
export const handlerLabel = (handler: string | null | undefined): string => (handler ? (HANDLERS[handler] ?? words(handler)) : "");

/** When a task runs, from its run condition; a missing condition means every upstream task must succeed. */
export function runConditionLabel(condition: string | null | undefined, required?: number | null): string {
  if (!condition || condition === "ALL") return "all upstream succeed";
  if (condition === "ANY") return "any upstream succeeds";
  if (condition === "N") return required ? `at least ${required} upstream succeed` : "the required number of upstream succeed";
  return words(condition).toLowerCase();
}

/** Search task details name the handler in words; the API and exports keep the engine code. */
export const searchDetail = (hit: { kind: string; detail: string }): string =>
  hit.kind === "TASK" ? hit.detail.replace(/^\S+(?= in )/, handlerLabel) : hit.detail;
