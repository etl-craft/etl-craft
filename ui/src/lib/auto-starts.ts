const EVERYTHING = "SCHEDULE|ALWAYS";
const ENDINGS = ["SUCCESS", "SKIPPED", "FAILURE"];

export interface AutoStarts {
  /** Whether a pipeline's schedule starts runs here. */
  schedule: boolean;
  /** The run endings that start the next run; empty when none does. */
  endings: string[];
  /** Nothing starts a run by itself. */
  off: boolean;
  /** Something is narrower than the default. */
  limited: boolean;
}

const parts = (value: string): string[] => (value === "NONE" ? [] : value.split("|"));
const endingsOf = (value: string): string[] => (parts(value).includes("ALWAYS") ? ENDINGS : ENDINGS.filter((e) => parts(value).includes(e)));

/** The setting's value in plain words: "everything", "nothing", or what it names. */
export function describeAutoStarts(value: string | undefined): string {
  if (value === undefined) return "unknown";
  if (value === EVERYTHING) return "everything";
  if (value === "NONE") return "nothing";
  const named = parts(value).map((p) => (p === "SCHEDULE" ? "schedules" : p === "ALWAYS" ? "every ending" : `after ${p.toLowerCase()}`));
  return named.join(", ");
}

/** What starts runs by itself in a project: the narrower of the controller's setting and the project's own. */
export function autoStarts(controller: string | undefined, project: string | undefined): AutoStarts | undefined {
  if (controller === undefined && project === undefined) return undefined;
  const both = [controller ?? EVERYTHING, project ?? EVERYTHING];
  const schedule = both.every((v) => parts(v).includes("SCHEDULE"));
  const endings = ENDINGS.filter((e) => both.every((v) => endingsOf(v).includes(e)));
  return { schedule, endings, off: !schedule && endings.length === 0, limited: !schedule || endings.length < ENDINGS.length };
}
