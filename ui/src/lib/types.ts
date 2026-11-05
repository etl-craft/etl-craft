export type RunStatus = "IN-PROGRESS" | "SUCCESS" | "FAILED" | "SKIPPED" | "LOST" | "STOPPED" | "ABORTED" | "HELD" | string;

export interface Identity {
  name: string;
  role: "admin" | "operator" | "viewer" | string;
  must_change_password: boolean;
  project_permission: string | null;
  settings: { theme: string; timezone: string; default_project: string | null; page_size: number; time_display: string };
}

export interface ProjectCounts {
  project: string;
  project_name: string;
  environment_type: string;
  environment_name: string | null;
  governance: string;
  running: number;
  failed: number;
  sla_misses: number;
  queued_tasks: number;
}

export interface ProjectHealth {
  window_start: string;
  window_end: string;
  projects: ProjectCounts[];
}

export interface RunView {
  pipeline_code: string;
  pipeline_run_id: number;
  run_key: string;
  trigger_kind: string;
  run_date: string | null;
  status: RunStatus;
  start_date: string | null;
  end_date: string | null;
  sla_status: string | null;
  backfill: boolean;
  started_by: string | null;
  ended_by: string | null;
  parent_run_id: number | null;
  child_run_ids: number[];
  newer_metadata_available: boolean;
}

export interface History {
  entries: RunView[];
  before: number | null;
}

export interface PipelineView {
  pipeline_code: string;
  pipeline_name: string;
}

export interface StepView {
  task_code: string;
  task_run_id: number | null;
  task_type: string;
  handler: string;
  run_condition: string | null;
  status?: RunStatus;
}

export interface Steps {
  steps: StepView[];
}

export interface Graph {
  waves: string[][];
  conditional: string[];
  depends_on: Record<string, [string, string][]>;
}

export interface AttemptView {
  attempt_id: number;
  attempt_number: number;
  status: string;
  queued_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  host: string | null;
  exit_code: number | null;
  rows_written: number | null;
  error_message: string | null;
  failure_class: string;
  retry_on: string | null;
}

export interface TaskRunView {
  task_code: string;
  status: RunStatus;
  start_date: string | null;
  end_date: string | null;
  attempt_count: number;
  error_message: string | null;
  attempts: AttemptView[];
}

export interface TaskHistory {
  entries: TaskRunView[];
}

export interface Capability {
  action: string;
  available: boolean;
  reason: string | null;
}

export interface Capabilities {
  actions: Capability[];
}

export interface ControlView {
  control_id: number;
  pipeline_run_id: number;
  action: string;
  status: string;
  message: string;
  run_status: RunStatus;
  execution_run_id: number | null;
}
