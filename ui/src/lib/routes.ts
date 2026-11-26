/** Every in-app address is built here, so a page never assembles its own path. */
const enc = encodeURIComponent;

export const homePath = "/";
/** Every project the account can see, as cards. */
export const projectsPath = "/projects";
/** A project's own home: its status card, so Home never leaves the project. */
export const projectHomePath = (project: string): string => `/projects/${enc(project)}`;
export const runsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/runs` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
/** Open a run, optionally with its task panel selected. */
export const runPath = (project: string, pipeline: string, runId: number | string, task?: string): string =>
  runBase(project, pipeline, runId) + (task ? `?task=${enc(task)}` : "");
/** The run address also anchors attempts and task items. */
export const runBase = (project: string, pipeline: string, runId: number | string): string =>
  `/projects/${enc(project)}/runs/${enc(pipeline)}/${enc(String(runId))}`;
export const pipelinesPath = (project: string, tags: string[] = []): string =>
  `/projects/${enc(project)}/pipelines` + (tags.length ? "?" + tags.map((t) => `tag=${enc(t)}`).join("&") : "");
export const pipelinePath = (project: string, pipeline: string, tab?: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}` + (tab ? `?tab=${tab}` : "");
/** Return to a pipeline's workspace with one run selected. */
export const pipelineRunPath = (project: string, pipeline: string, runId: number | string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}?run=${enc(String(runId))}`;
export const scheduledPath = (project: string, pipeline?:string): string => `/projects/${enc(project)}/scheduled` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
export const pausedPath = (project: string): string => `/projects/${enc(project)}/paused`;
export const taskPath = (project: string, pipeline: string, task: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}/tasks/${enc(task)}`;
export const attemptPath = (project: string, pipeline: string, runId: number | string, task: string, attemptId: number | string): string =>
  `${runBase(project, pipeline, runId)}/tasks/${enc(task)}/attempts/${attemptId}`;
export const itemsPath = (project: string, pipeline: string, runId: number | string, task: string): string =>
  `${runBase(project, pipeline, runId)}/tasks/${enc(task)}/items`;
export const uploadsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/uploads` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
export const consolePath = (project: string): string => `/projects/${enc(project)}/console`;
export type CatalogKind = "pipelines" | "tasks" | "tables" | "gaps";
/** The catalog, or one object in it: a pipeline, a task (`PIPELINE.task`), a table (`schema.table`) or the gaps. */
export const catalogPath = (project: string, kind?: CatalogKind, name?: string, tab?: string): string =>
  `/projects/${enc(project)}/catalog` + (kind ? `/${kind}` + (name ? `/${enc(name)}` : "") : "") + (tab ? `?tab=${tab}` : "");
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
