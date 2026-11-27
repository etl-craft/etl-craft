/** Engine codes in the words a page shows: the code stays in the data, exports and the CLI. */

/** `FILE_VALIDATION` → "File validation": a code nobody has given a label, in words. */
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
  BUSINESS_RULES: "Business rules",
  ALERT: "Alert",
  EVENT_WAIT: "Event wait",
  RUN_PIPELINE: "Run pipeline",
};

/** What runs a task, as a person names it. */
export const handlerLabel = (handler: string | null | undefined): string => (handler ? (HANDLERS[handler] ?? words(handler)) : "");

/** Search task details name the handler in words; the API and exports keep the engine code. */
export const searchDetail = (hit: { kind: string; detail: string }): string =>
  hit.kind === "TASK" ? hit.detail.replace(/^\S+(?= in )/, handlerLabel) : hit.detail;
