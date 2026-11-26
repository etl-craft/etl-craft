export type RunStatus = "IN-PROGRESS" | "SUCCESS" | "FAILED" | "SKIPPED" | "LOST" | "STOPPED" | "ABORTED" | string;

export interface Identity {
  name: string;
  role: "admin" | "operator" | "viewer" | string;
  must_change_password: boolean;
  local_password: boolean;
  last_signin: string | null;
  session_expires_at: string | null;
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  names_editable?: boolean;
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
  allowed_auto_restarts: string;
}

export interface ProjectHealth {
  window_start: string;
  window_end: string;
  projects: ProjectCounts[];
}

export interface RunView {
  selected_task_ids?: number[];
  parameter_overrides?: Record<string, Record<string, string>>;
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
  full_refresh: boolean;
  started_by: string | null;
  ended_by: string | null;
  parent_run_id: number | null;
  child_run_ids: number[];
  newer_metadata_available: boolean;
  /** Recorded queue, wait and execution intervals; only the single-run read fills it. */
  timeline?: TimelineSegment[];
}

export type TimelineKind = "QUEUE" | "GATE" | "EVENT" | "CHILD_RUN" | "EXECUTION";

/** One recorded interval of a run; `ended_at` is null while open or when the wait stopped with its run. */
export interface TimelineSegment {
  task_code: string | null;
  kind: TimelineKind;
  started_at: string;
  ended_at: string | null;
  outcome: string;
  attempt_number: number | null;
  deadline: string | null;
}

export interface GridCell {
  task_code: string;
  task_run_id: number;
  pipeline_run_id: number;
  status: string;
  attempt_count: number;
  attempt_id: number | null;
  start_date: string | null;
  end_date: string | null;
  task_run_label: string;
}

export interface History {
  task_order?: string[];
  cells?: GridCell[];
  extra_run?: RunView | null;
  entries: RunView[];
  before: number | null;
}

export interface StepView {
  parameters?: Record<string, string>;
  task_code: string;
  task_run_id: number | null;
  task_type: string;
  handler: string;
  run_condition: string | null;
  run_condition_count?: number | null;
  status?: RunStatus;
  task_run_label?: string;
}

export interface Steps {
  source?: { version: string; file: string | null; text: string | null; truncated_at_bytes: number | null };
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
  run_label?: string;
  task_run_label?: string;
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
  run_label?: string;
  task_run_label?: string;
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
  pending_task_run_label?: string;
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
  task_run_id: number;
  task_run_label?: string;
  records: ItemRecord[];
  availability: { action: string; item_key: string | null; available: boolean; reason: string }[];
  progress: { total: number; done: number; failed: number; skipped: number };
}

export interface Capability {
  action: string;
  available: boolean;
  reason: string;
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
  execution_run_label?: string;
  run_label?: string;
}

export type ActiveRuns = "DRAIN" | "FINISH";

export interface Pause {
  active_runs: ActiveRuns;
  drained_runs: { pipeline_run_id: number; run_label: string; status: RunStatus }[];
  paused_at: string;
  paused_by: string;
  reason: string;
}

export interface TaskPause {
  task_code: string;
  outcome: "SUCCESS" | "SKIPPED" | "FAILED";
  expires_at: string | null;
  paused_at: string;
  actor: string;
  reason: string;
}

export interface RecentRun {
  pipeline_run_id: number;
  status: RunStatus;
  sla_status: string | null;
  /** Absent from a server that predates them. */
  start_date?: string | null;
  end_date?: string | null;
  run_label?: string;
}

export interface Pipeline {
  depends_on: [string, string][];
  alert_deliveries?: AlertDelivery[];
  latest_whole_run?: RecentRun | null;
  starts_on_upload?: boolean;
  waits_for_events?: boolean;
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
  run_label?: string;
}

export interface UploadReceipt {
  upload_id: number;
  pipeline_run_id: number | null;
  waiting_behind_run_id: number | null;
  waiting_behind_run_label?: string;
  run_label?: string;
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

/** What a lineage re-parse answers: every task traced again, and which of them could not be. */
export interface LineageReparse {
  lineages: TaskLineage[];
  failed: boolean;
}

export interface ControllerVersion {
  controller_id: number;
  version: string;
  heartbeat_at: string;
  allowed_auto_restarts: string;
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
  run_label?: string;
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
  first_name: string | null;
  last_name: string | null;
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

/** One access binding: WHO (account, group or audience) gets WHAT (role or one action) WHERE. */
export interface Binding {
  scope: "DEPLOYMENT" | "ENVIRONMENT" | "PROJECT";
  project: string | null;
  environment: string | null;
  group: string | null;
  account: string | null;
  audience: string | null;
  pipeline: string | null;
  tag: string | null;
  role: string | null;
  action: string | null;
  active_flag: string;
}

/** A named set of actions; built-in CAN_* roles list what they allow but cannot change. */
export interface RoleView {
  name: string;
  description: string | null;
  built_in: boolean;
  active_flag: string;
  actions: string[];
}

export interface ProjectRow {
  alert_deliveries?: AlertDelivery[];
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
  allowed_auto_restarts: string;
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
  browser_sso?: boolean;
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

export interface TablePreview {
  table: string;
  columns: string[];
  rows: (string | null)[][];
  limit: number;
  more: boolean;
}

export interface AlertDelivery {
  delivery_id: number;
  event_id?: string;
  channel: string;
  pipeline_code: string;
  source_run_id: number;
  source_run_label: string;
  alert_run_id: number;
  alert_run_label: string;
  trigger: string;
  attempt_number: number;
  status: string;
  status_code: number | null;
  error_class: string | null;
  created_at: string;
}
