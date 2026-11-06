/** Every in-app address is built here, so a page never assembles its own path. */
const enc = encodeURIComponent;

export const homePath = "/";
export const runsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/runs` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
export const runPath = (project: string, pipeline: string, runId: number | string): string =>
  `/projects/${enc(project)}/runs/${enc(pipeline)}/${runId}`;
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
export const uploadsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/uploads` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
export const insightsPath = (project: string): string => `/projects/${enc(project)}/insights`;
export const consolePath = (project: string): string => `/projects/${enc(project)}/console`;
export const catalogPath = (project: string, page?: string): string => `/projects/${enc(project)}/catalog` + (page ? `?page=${enc(page)}` : "");
/** The generated catalog site, served by the same-origin file route. */
export const catalogSite = (project: string, page = "index.html"): string => `/ui/projects/${enc(project)}/catalog/files/${page}`;
export const systemPath = "/system";
export const agentsPath = "/agents";
export const adminPath = (tab = "accounts", project?: string): string => `/admin?tab=${tab}` + (project ? `&project=${enc(project)}` : "");
export const aboutPath = "/about";
export const settingsPath = "/settings";
export const passwordPath = "/password";
export const searchPath = (project: string, q = ""): string => `/projects/${enc(project)}/search` + (q ? `?q=${enc(q)}` : "");
export const maintenancePath = (project: string): string => `/projects/${enc(project)}/maintenance`;
