export type RunStatus = "IN-PROGRESS" | "SUCCESS" | "FAILED" | "SKIPPED" | "LOST" | "STOPPED" | "ABORTED" | "HELD" | string;

export interface Identity {
  name: string;
  role: "admin" | "operator" | "viewer" | string;
  must_change_password: boolean;
  local_password: boolean;
  last_signin: string | null;
  session_expires_at: string | null;
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
  /** Pipeline, UTC start and run id, fixed when the run was created; empty on a server that predates it. */
  run_label?: string;
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
  pipeline_run_id: number;
  task_run_id: number;
  status: string;
  owner_id: string | null;
  queued_at: string | null;
  claimed_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  host: string | null;
  pid: number | null;
  exit_code: number | null;
  source_count: number | null;
  target_count: number | null;
  insert_count: number | null;
  update_count: number | null;
  delete_count: number | null;
  rows_written: number | null;
  reject_count: number | null;
  duplicate_count: number | null;
  watermark_from: string | null;
  watermark_to: string | null;
  error_message: string | null;
  failure_class: string;
  failure_source: string | null;
  failure_code: string | null;
  retry_on: string | null;
  retry_reason: string | null;
  retryable: boolean;
  log_path: string | null;
  process_evidence_kind: string | null;
  process_evidence_actor: string | null;
  process_evidence_reason: string | null;
  query_evidence_kind: string | null;
  query_evidence_actor: string | null;
  query_evidence_reason: string | null;
}

export interface TaskRunView {
  task_code: string;
  task_run_id: number;
  pipeline_run_id: number;
  status: RunStatus;
  start_date: string | null;
  end_date: string | null;
  attempt_count: number;
  source_count: number | null;
  target_count: number | null;
  insert_count: number | null;
  update_count: number | null;
  delete_count: number | null;
  rows_written: number | null;
  reject_count: number | null;
  duplicate_count: number | null;
  error_message: string | null;
  attempts: AttemptView[];
  item_progress: string | null;
}

export interface TaskHistory {
  entries: TaskRunView[];
}

export interface TaskDefinition {
  task_code: string;
  handler: string;
  parameters: Record<string, string>;
  merge_key: string[];
  merge_columns: string[];
}

export interface TaskOffset {
  kind: string | null;
  offset_type: string | null;
  offset_value: string | null;
  pending_task_run_id: number | null;
  pending_upper_bound: string | null;
}

export interface Dependency {
  upstream: string;
  dependency_type: string;
  status: string | null;
  met: boolean;
  reason: string;
}

export interface Explanation {
  run_condition: string;
  required_count: number;
  dependencies: Dependency[];
  retry_at: string | null;
}

export interface ItemRecord {
  key: string;
  status: string;
  row_count: number | null;
  error: string | null;
  started: string | null;
  ended: string | null;
}

export interface Items {
  records: ItemRecord[];
  progress: { total: number; done: number; failed: number; skipped: number };
}

export interface Capability {
  action: string;
  available: boolean;
  reason: string | null;
  preserves_successful_work: boolean;
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

export interface Pause {
  paused_at: string;
  paused_by: string;
  reason: string;
}

export interface TaskPause {
  task_code: string;
  outcome: string | null;
  expires_at: string | null;
  paused_at: string;
  actor: string;
  reason: string;
}

export interface RecentRun {
  pipeline_run_id: number;
  status: RunStatus;
  sla_status: string | null;
}

export interface Pipeline {
  pipeline_code: string;
  pipeline_name: string;
  refresh_type: string;
  run_schedule: string | null;
  /** What may start it on its own; absent from a server that predates the setting. */
  auto_restart_condition?: string;
  /** The condition in words when it adds to or replaces the schedule; null for the schedule alone. */
  restart_note?: string | null;
  /** What the pipeline does (its `DESCRIPTION`); absent from a server that predates it. */
  description?: string | null;
  sla_in_hours: number | null;
  paused: Pause | null;
  tags: string[];
  task_pauses: TaskPause[];
  next_run: string | null;
  schedule_problem: string | null;
  recent_runs: RecentRun[];
}

export interface Hold {
  control_id: number;
  pipeline_run_id: number;
  pipeline_code: string;
  task_code: string | null;
  requested_by: string;
  reason: string | null;
  requested_at: string;
}

export interface BulkOutcome {
  pipeline_code: string;
  error?: string | null;
}

export interface UploadRow {
  upload_id: number;
  account: string;
  file_name: string;
  stored_name: string | null;
  size_bytes: number;
  pipeline_run_id: number | null;
  status: string;
  reason: string | null;
  uploaded_at: string;
  run_status: string | null;
}

export interface UploadReceipt {
  upload_id: number;
  pipeline_run_id: number | null;
  waiting_behind_run_id: number | null;
}

export interface ValueResult {
  target: string;
  enabled: boolean;
  records: Record<string, unknown>[];
  history: Record<string, unknown>[];
}

export interface DayInsight {
  day: string;
  runs: number;
  succeeded: number;
  failed: number;
  average_seconds: number | null;
}

export interface PipelineInsight {
  pipeline_code: string | null;
  runs: number;
  succeeded: number;
  failed: number;
  finished: number;
  in_progress: number;
  success_rate: number | null;
  average_seconds: number | null;
  longest_seconds: number | null;
  sla_breached: number;
  attempts: number;
  retries: number;
  lost_attempts: number;
  rows_written: number | null;
  rows_per_second: number | null;
  average_wait_seconds: number | null;
  average_run_seconds: number | null;
}

export interface TaskInsight {
  pipeline_code: string;
  task_code: string;
  runs: number;
  source_rows: number | null;
  target_rows: number | null;
  inserted: number | null;
  updated: number | null;
  deleted: number | null;
  rejected: number | null;
}

export interface FailureInsight {
  pipeline_code: string;
  task_code: string;
  status: string;
  failure_class: string | null;
  attempts: number;
}

export interface RuleObservation {
  observed: string;
  passed: string;
}

export interface RuleInsight {
  pipeline_code: string;
  rule_name: string;
  runs: number;
  failed: number;
  passed: number;
  not_passed: number;
  flagged_rows: number;
  observations: RuleObservation[];
}

export interface GapInsight {
  attribute: string;
  state: string;
  checks: number;
}

export interface Insights {
  window_start: string;
  window_end: string;
  pipelines: string[];
  total: PipelineInsight;
  per_pipeline: PipelineInsight[];
  days: DayInsight[];
  tasks: TaskInsight[];
  failures: FailureInsight[];
  rules: RuleInsight[];
  latest: RunView[];
  gaps: GapInsight[];
  gaps_compared_at: string | null;
  schema_check_schedule: string | null;
  schema_check_on_demand: boolean;
}

export interface Finding {
  severity?: string;
  message: string;
}

export interface Report {
  pipelines: number;
  tasks: number;
  findings: Finding[];
}

export interface AuditAction {
  action_id: number;
  at: string;
  command: string;
  outcome: string;
}

export interface ConsoleResult {
  exit_code: number;
  output: string;
  error: string;
}

export interface TaskLineage {
  task: string;
  error: string | null;
  cached: boolean;
}

/** What a lineage refresh answers: every task traced again, and which of them could not be. */
export interface LineageRefresh {
  lineages: TaskLineage[];
  failed: boolean;
}

export interface ControllerVersion {
  controller_id: number;
  version: string;
  heartbeat_at: string;
}

export interface About {
  package_version: string;
  schema_version: string | null;
  server_version: string;
  controllers: ControllerVersion[];
  license: string;
  docs_url: string;
}

export interface AgentRow {
  agent_id: number;
  pool: string;
  host: string;
  version: string;
  status: "ACTIVE" | "DRAINING" | "GONE" | string;
  heartbeat_at: string;
  attempts: number[];
  free_cpu: number;
  free_memory_mb: number;
  pending_commands: { command?: string }[];
}

export interface PoolCapacity {
  pool: string;
  agents: number;
  advertised_cpu: number;
  advertised_memory_mb: number;
  free_cpu: number;
  free_memory_mb: number;
}

export interface AgentsView {
  agents: AgentRow[];
  pools: PoolCapacity[];
}

export interface PersonalSettings {
  theme: string;
  timezone: string;
  default_project: string | null;
  page_size: number;
  time_display: string;
}

export interface SearchHit {
  kind: "PIPELINE" | "TASK" | "RUN" | "TABLE" | string;
  label: string;
  detail: string;
  pipeline_code: string | null;
  run_id: number | null;
  catalog_path: string | null;
}

export interface SearchView {
  q: string;
  hits: SearchHit[];
  truncated: boolean;
}

export interface Account {
  account_id: number;
  name: string;
  kind: string;
  role: string;
  email: string | null;
  active_flag: string;
  failed_signins: number;
  locked_at: string | null;
  last_signin_at: string | null;
}

export interface Group {
  group_id: number;
  name: string;
  description: string | null;
  active_flag: string;
  members: string[];
}

export interface TokenRow {
  token_id: number;
  name: string;
  token_kind: string;
  role: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface Grant {
  project: string;
  group: string | null;
  account: string | null;
  role: string | null;
  pipeline: string | null;
  tag: string | null;
  permission: string;
  active_flag: string;
}

export interface ProjectRow {
  project: string;
  name: string;
  timezone: string;
  default_pool: string;
  max_running_tasks: number;
  active_flag: string;
  environment_type: string;
  environment_name: string | null;
  governance: string;
  schema_check_schedule: string | null;
  schema_check_on_demand: string;
}

export interface PoolRow {
  name: string;
  description: string | null;
  active_flag: string;
}

export interface Announcement {
  announcement_id: number;
  level: string;
  message: string;
  starts_at: string;
  ends_at: string | null;
  created_by: string;
  ended_by: string | null;
  ended_at: string | null;
}

export interface SignInMethods {
  sso: boolean;
  local: boolean;
  contact: string | null;
  notice: string | null;
}

export interface SsoStart {
  user_code: string;
  verification_uri: string;
  device_code: string;
  nonce: string;
  interval: number;
  expires_in: number;
}

export interface Redirect {
  redirect?: string;
  interval?: number;
}

export interface AuditActionRecord {
  action_id: number;
  at: string;
  actor: string;
  kind: string;
  command: string;
  outcome: string;
}

export interface AuditChangeRecord {
  change_id: number;
  at: string;
  actor: string;
  table_name: string;
  operation: string;
}

export interface AuditRecords {
  actions: AuditActionRecord[];
  changes: AuditChangeRecord[];
}
