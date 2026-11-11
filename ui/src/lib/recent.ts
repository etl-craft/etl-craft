/** Pipelines and runs opened in this browser, newest first, kept per project. */
export interface Recent {
  path: string;
  label: string;
}

const key = (project: string) => `etl-craft-recent-${project}`;
const LIMIT = 8;

export function readRecent(project: string): Recent[] {
  try {
    return JSON.parse(window.localStorage.getItem(key(project)) ?? "[]") as Recent[];
  } catch {
    return [];
  }
}

/** Remember the page when it is a pipeline or a run; any other page is ignored. */
export function rememberVisit(project: string, pathname: string): void {
  const run = /^\/projects\/[^/]+\/runs\/([^/]+)\/(\d+)$/.exec(pathname);
  const pipeline = /^\/projects\/[^/]+\/pipelines\/([^/]+)$/.exec(pathname);
  const label = run ? `${decodeURIComponent(run[1] ?? "")} run ${run[2]}` : pipeline ? decodeURIComponent(pipeline[1] ?? "") : null;
  if (!label) return;
  try {
    const kept = readRecent(project).filter((r) => r.path !== pathname);
    window.localStorage.setItem(key(project), JSON.stringify([{ path: pathname, label }, ...kept].slice(0, LIMIT)));
  } catch {
    /* recent pages are a convenience; the page works without them */
  }
}
