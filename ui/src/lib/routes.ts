/** Every in-app address is built here, so a page never assembles its own path. */
const enc = encodeURIComponent;

export const homePath = "/";
export const runsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/runs` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
export const runPath = (project: string, pipeline: string, runId: number | string): string =>
  `/projects/${enc(project)}/runs/${enc(pipeline)}/${runId}`;
/** Pages of the existing interface, until their slice is rebuilt. */
export const existingPath = (project: string, page: string): string => `/ui/projects/${enc(project)}/${page}`;
export const pipelinesPath = (project: string, tags: string[] = []): string =>
  `/projects/${enc(project)}/pipelines` + (tags.length ? "?" + tags.map((t) => `tag=${enc(t)}`).join("&") : "");
export const pipelinePath = (project: string, pipeline: string, tab?: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}` + (tab ? `?tab=${tab}` : "");
export const scheduledPath = (project: string): string => `/projects/${enc(project)}/scheduled`;
export const heldPath = (project: string): string => `/projects/${enc(project)}/held`;
export const taskPath = (project: string, pipeline: string, task: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}/tasks/${enc(task)}`;
export const attemptPath = (project: string, pipeline: string, runId: number | string, task: string, attemptId: number | string): string =>
  `${runPath(project, pipeline, runId)}/tasks/${enc(task)}/attempts/${attemptId}`;
export const itemsPath = (project: string, pipeline: string, runId: number | string, task: string): string =>
  `${runPath(project, pipeline, runId)}/tasks/${enc(task)}/items`;
