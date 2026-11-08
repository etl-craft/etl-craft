/** Every in-app address is built here, so a page never assembles its own path. */
const enc = encodeURIComponent;

export const homePath = "/";
/** Every project the account can see, as cards. */
export const projectsPath = "/projects";
/** A project's own home: its status card, so Home never leaves the project. */
export const projectHomePath = (project: string): string => `/projects/${enc(project)}`;
export const runsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/runs` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
/** A run is its pipeline's workspace with the run selected; `task` opens one task of it. */
export const runPath = (project: string, pipeline: string, runId: number | string, task?: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}?run=${runId}` + (task ? `&task=${enc(task)}` : "");
/** The address an attempt or a task's items hang from, and the one older links to a run use. */
export const runBase = (project: string, pipeline: string, runId: number | string): string =>
  `/projects/${enc(project)}/runs/${enc(pipeline)}/${runId}`;
export const pipelinesPath = (project: string, tags: string[] = []): string =>
  `/projects/${enc(project)}/pipelines` + (tags.length ? "?" + tags.map((t) => `tag=${enc(t)}`).join("&") : "");
export const pipelinePath = (project: string, pipeline: string, tab?: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}` + (tab ? `?tab=${tab}` : "");
/** A pipeline's runs with one run highlighted: where the project's run list leads. */
export const pipelineRunPath = (project: string, pipeline: string, runId: number | string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}?run=${runId}`;
export const scheduledPath = (project: string): string => `/projects/${enc(project)}/scheduled`;
export const heldPath = (project: string): string => `/projects/${enc(project)}/held`;
export const taskPath = (project: string, pipeline: string, task: string): string =>
  `/projects/${enc(project)}/pipelines/${enc(pipeline)}/tasks/${enc(task)}`;
export const attemptPath = (project: string, pipeline: string, runId: number | string, task: string, attemptId: number | string): string =>
  `${runBase(project, pipeline, runId)}/tasks/${enc(task)}/attempts/${attemptId}`;
export const itemsPath = (project: string, pipeline: string, runId: number | string, task: string): string =>
  `${runBase(project, pipeline, runId)}/tasks/${enc(task)}/items`;
export const uploadsPath = (project: string, pipeline?: string): string =>
  `/projects/${enc(project)}/uploads` + (pipeline ? `?pipeline=${enc(pipeline)}` : "");
export const consolePath = (project: string): string => `/projects/${enc(project)}/console`;
export type CatalogKind = "pipelines" | "tasks" | "tables" | "gaps" | "insights";
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
