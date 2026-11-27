# Monitoring and operability for 0.9.0

Status: proposed for owner review. Evidence baseline: `c9f39e62`. Frequency below describes expected use at a site with hundreds of production loads. The demo establishes behavior, and usage frequency still needs owner confirmation.

At shift handoff an operator needs a list of incidents across authorized projects. During an incident they need the exact attempt, what reached the target, why the next task has not started, and what recovery will touch. During normal hours an engineer needs enough provenance to explain a change and enough bounded history to spot drift. Keep pipelines in code, execution order in dependency rows, and authorization and decisions in one operation shared by callers.

## Run, task and log evidence

**Before 0.9.0.** Every failed load creates triage work. The demo failed-run card already identifies `flaky_feed` and opens the task. `ui/src/pages/run.tsx`, `components/grid-task-details.tsx`, `components/run-overview.tsx` and `services/operations/run_log.py` already provide the run workspace, attempt context, links and lifecycle log. `task_run_facts.sql`, `operation_attempts.sql`, `AUD_TASK_RUN_LOG` and `AUD_TASK_ATTEMPTS` have counts, timings and failure classes. Preserve existing recovery and raw log downloads. Extend the same task panel and run workspace.

- Show selected try, class, stable symbolic code sourced from the typed error at capture, and first and last recorded error with step and durable attempt/offset anchors. A terminal summary alone cannot reconstruct the first error. Return “First error was not recorded for attempt 12. Open the raw log for recorded detail.” Keep the terminal result visible if an individual log is expired or unavailable. Display an unexpected failure with its recorded generic code and redacted message. Never infer failure class from stderr text.
- Show emitted source read/failure and target applied/affected/insert/update/delete/reject/duplicate counters using handler definitions. Preserve count zero. Omit unsupported metrics and label missing telemetry on otherwise supported handlers. Display execution duration and measured rows/s only with a known numerator and positive elapsed interval. Compare the same task, handler, target and compatible definition with up to 20 successful normal runs in 30 days, showing sample size and excluding backfills and replays. With fewer than five comparable runs, display “Baseline unavailable (3 comparable runs).”
- Run Statistics is sortable with one task per row, showing the final attempt and expandable previous tries. Keep applied counts and rejected counts separate. Avoid a cross-task “rows loaded” total that adds the same rows at successive stages. Cap a page at 100 rows. Keep task status and recovery independent of sort order.
- Keep raw and structured log views together. Structured events come from known execution points such as condition evaluations and statement boundaries. Record severity, step, timestamp, event code, attempt and sequence or byte anchor, with redacted fields. Legacy lines and arbitrary script output remain searchable in the selected raw stream with severity “Unknown”. First-error navigation opens the recorded event and can reset an excluding filter explicitly. Window and cursor apply to the selected stream, with 200 events per page. Expired lines show “Attempt 12 log expired on [date].” A storage outage says which stream failed and offers retry.

Use one run response for initial context and one selected-task response including statistics and failure, with at most two added set-based SQL statements per read above the separately captured baseline. Use one request per log window and at most two data statements after scope resolution. Prefer bounded typed events in the existing attempt log/spool and compact failure anchors on the attempt row in both schemas. Persist anchors with the terminal outcome, and derive the historical median only when a task is selected. Use plain offsets plus retention checks, with continuation after the same ordered event, including identical timestamps. No new CLI verb. Existing exact-run status/history/log surfaces can expose the data after output approval. Size: three implementation PRs for data, run/task UI and logs. Tests: empty versus zero, incompatible baseline, network/log loss, first error before terminal error, unknown severity, retry ordering, permissions, both schemas and breakpoint/theme checks.

## Waiting, agents and live incidents

**Before 0.9.0.** Operators check waiting work every shift and whenever throughput drops. `placement_wait_reasons.sql`, `AUD_GATE_WAITS`, `services/operations/agent_capacity.py`, `agent_reports.py`, `task_pauses.py` and `ui/src/pages/agents.tsx` distinguish capacity, leases and some wait causes. Reuse these decisions. A local controller without registered agents is a valid deployment. Add deployment-aware empty text and links to System health.

- Show why and since when for a recorded pool or connection wait, gate/event, retry delay, task pause or fence. Display deadline/next evaluation when recorded. A single run can have concurrent running and waiting tasks. Keep the run state and task wait distinct. “Placement reason unavailable. Last evaluated at 02:18 UTC” handles stale or missing evidence. Omit queue position because eligibility and competing claims can change. Never call a pause or wait “suspended.” Suspend on error is a separate deferred transition.
- Extend Agents with bounded, expandable current attempts, pool, used/free eligible slots, last heartbeat and read timestamp. Match the attempt to the current owner and birth identity. PID and process resource evidence stay with authorized operators. Persist attempt peak RSS and CPU seconds on the attempt when sampled. Live agent samples show current RSS and interval CPU in cores, with sample age and limits. Omit swap until the sampling source and platform can report what it means. Separate agent process metrics from warehouse execution. Reuse the installed psutil process identity and CPU/RSS facilities (see `core/agent_resources.py` and `execution/leases.py`). The stdlib Unix `resource` interface can describe completed children in constrained single-child deployments, but aggregate child usage cannot be attributed to an attempt when children overlap. Label unavailable on unsupported platforms. Never guess whether a lost worker hit its memory limit.
- Add a Monitor destination under Operations and use the existing project Home for analytics. Scope is projects visible to the account. Default to active work plus failures ended in the last 24 hours, with 7 days as the proposed maximum for recent failures. Show running, waiting, failed and late categories as filter chips. Derive late from the run's recorded SLA policy and existing SLA clock while it is active, and distinguish completed breaches from active overdue work. A run with no applicable SLA stays out of late. Missed scheduled occurrences without a run are deferred because “no run” requires schedule expectation evidence. No all-project bulk actions. Counts, where included, use the same visibility and time bounds as rows. Prefer “More results” over an expensive exact total.

Use one request per Monitor page or refresh, 50 rows ordered by bucket and stable timestamp/id, at most three data statements after scope resolution, including wait hydration. Keep older active rows reachable even if they started before the terminal lookback. Use a snapshot timestamp and bound cursor to scope/filter; reject changed scope or an invalid continuation with “Filters changed. Start again from the first page.” Use existing project permission checks in SQL before selecting rows or calculating aggregates. Poll the visible page every 15 seconds, suspend polling in background, and show the last successful refresh after outage. Agent list stays one request with a pool cursor and one capped expanded agent query, at most two added data statements per view. Do not add a sample-history table. Size: one PR for waits/agent data and page, one for Monitor and active SLA. Tests: authorization changes, redacted blockers across projects, stale heartbeats, lease transfer, no-agent mode, retry timing, clock and deadline boundaries, active work older than lookback, equal timestamps, no polling offscreen, and layout checks.

**After 0.9.0, placed after 1.0.0.** Weekly ETL maintenance uses duration and row-count trends and comparison after a deployment. Home already shows duration and rows from `services/operations/insights.py`. Retain those views. Add per-task drift with comparable recent points, and compare two explicit run IDs and their pinned versions, redacted parameters, attempts and counts in the existing pipeline/run workspace. No default baseline picked by recency for recovery or comparison. Use one request per chart/compare, at most four data statements and 30 days or 30 points. Test sparse history, revision, incompatible counts and partial retention. Size: two PRs, query changes, optional summary only after measurement, read API/CLI output review and UI tabs. Cross-run log search also moves after 1.0.0. Start with indexed typed codes and a required project/time filter, ≤7 days and 50 hits per page in one request and ≤2 data reads. Test unauthorized hits, stable anchors and expired evidence. A full-text index of arbitrary user log content is rejected for now. It requires redaction guarantees, access-aware retention and write/storage evidence. A bounded Python scan of arbitrarily large files is also inappropriate for an interactive cross-run query.

## Recovery, alerts, audit and support

**Before 0.9.0.** Every terminal failure or expired lease requires a decision. `services/operations/recovery.py`, `controls.py`, `previews.py`, `pipeline_resume.py` and `ui/src/components/run-recovery.tsx` already own preview and recovery. Keep explicit run identity, pinned definition, unchanged successes/skips, actor/reason, and server-side revalidation between preview and confirmation. Make the path from cause to the existing preview clear and add help to the Quick Start.

| Observed kind | Operator path and refusal |
| --- | --- |
| Transient connector failure, timeout or lost owner | Fix connectivity/capacity, check lease state, then inspect recovery preview. “Attempt 12 still has a live lease. Wait for reconciliation before retrying.” Identify unknown commit outcome before any replay. |
| Source, target, permissions or invalid definition | Show failing object and remedy. Explain the pinned version. A corrected deploy can require a fresh run using the new definition. “Run 3 pins version 7. Choose a new run to use version 8.” |
| Row rejection or failed rule | Review counts and existing rule/reject evidence, fix data, inspect replay and downstream consumption. Never treat a successful rule override as recovery. |
| Unmanaged SQL or external side effect with unknown result | Inspect the recorded statements and destination independently. Refuse a safety claim when a commit cannot be verified. Present the existing approved recovery actions with their consequences. |
| Waiting, paused, or condition false | Open blocker or condition evidence. Use existing unpause/override only where allowed. Explain intentionally skipped work from the recorded evaluation. |

`services/operations/alert_admission.py`, `alert_delivery.py`, `alert_history.py` and `AUD_ALERT_DELIVERIES` already handle configured delivery. `run_zip.py` already streams status, history, explanations and logs. `diagnostics.py` and `services/doctor.py` already check engine and schema/guards, artifact paths, warehouse, email, resources, budgets and eligible agents. `AUD_RUN_INTERVENTIONS`, typed history, `run_log.py` and the pipeline Audit log already answer many attribution questions. Do not add a support collector, duplicate action journal or invasive doctor probes.

Surface an incident handoff in the existing run: copy exact project/run/task/attempt IDs and a redacted link, link to the existing run download, audit and alert delivery, and use the existing doctor path for infrastructure. Explain when logs require further access. An empty delivery list distinguishes no matching recorded delivery from a known refusal/failure. The locally executed demo did not start a controller to dispatch mail, so the generic call to configure channels is a poor diagnosis. Add a short standard alert payload with exact identity, state, class if present, recorded deadline when relevant and an authorized deep link. Exclude log attachments, data, SQL text and secrets. Keep channel admission and dedupe by existing event identity. Missing trusted base URL yields exact IDs and “Run link unavailable. Open this run by ID.” Existing doctor checks take their normal budgets and remain outside dashboard refresh. Add read-only help for interpreting stale heartbeats and queue diagnostics, with no automatic external probe. For support ZIP at scale, measure the fan-out from one explanation per task and one read per attempt before optimizing. Keep streaming with authorization per artifact and clear omission evidence.

One PR, additive payload/UI changes and CLI/docs walkthrough, no table required. Reuse the selected run and existing alert/audit endpoints. No new read on initial load for collapsed support details. One bounded delivery/history read per opened panel with at most two data statements plus scope. Tests: viewer redaction, missing link, delivery dedupe/refusal, stale recovery preview, unavailable log, CLI explicit-selection walkthrough and keyboard/mobile recovery. Audit export, alert variables/attachments and recorded delivery escalation remain after 1.0.0. These matter to compliance and support during periodic reviews, but require a scope and retention contract. Initial export budget one cursor request and ≤3 data reads per 100 events with actor, before/after and UTC date. Test permissions and retention; estimate two later PRs.

## Scale and storage

Design for 50 projects, 5,000 pipelines and 200,000 logical task runs daily. Over 730 days that is 146 million task-run rows. At 10 tasks per pipeline run, expect 14.6 million pipeline-run rows. A 1.2 attempts/task assumption adds 175 million attempt rows, before log chunks, step evidence and intervention history. These are model inputs, not measured volumes. A 50-row response can still visit millions of rows.

| Path | Limit today and recommended gate |
| --- | --- |
| Runs, history, grid | `pipeline_run_history.sql` uses explicit visibility, ID cursor and limit. Pool/agent/class filters add a correlated attempt test. `history_cells.sql` fetches cells only for selected runs but has one attempt lookup per returned cell. Keep the existing cursor. Use a run-ID time or status leading index only after selective and unselective plans show fewer visited rows. Verify large task grids by bytes and returned cells as well as statements. |
| Catalog generation and lineage | `catalog_pipeline_runs.sql` and `catalog_task_runs.sql` rank history to keep recent rows per definition; returned rows are bounded per entity, work can still scale with history. Measure per-project predicate pushdown and indexed top-N by entity using existing catalog indexes. `diagnostics.py` builds the lineage graph from loaded lineage. `pipeline_reparse.py`, `AUD_PIPELINE_REPARSES` and `services/catalog/incremental.py` already give persisted parse data and incremental publication. |
| Home and Monitor | `operations/insights.py` and `insights_*.sql` aggregate project windows. Do not reuse those wide aggregations for an incident poll. For Monitor start with `ix_pipeline_runs_pending`; compare a terminal end-time/ID index with the existing plans. Use `ix_attempt_queue` and `ix_attempt_status_lease` for the existing placement and lease predicates. Measure restricted-project and broad-access plans and ensure visibility filtering happens before counts or limits. |
| Support and retention | `operations/run_zip.py` has per-task/per-attempt work. `operations/retention.py` already exposes maintenance. Retain existing project choices and legal/recovery holds, and benchmark purge batches away from shift change. Keep references for pinned definitions, held logs and live recovery. No implicit change to default history retention. |

**Before 0.9.0.** Bound new reads immediately and require measured plans before adding indexes. Capture cold/warm response bytes, time to first byte, examined rows and plans under 50-project visibility, one hot project, sparse failures and many retained runs. Measure the default window and deep keyset pagination. Proposed guardrails are 250 KiB for the first Monitor page, 500 ms local PostgreSQL p95 for a warm feed, and fixed statement count as projects/tasks grow. Revisit with observed hardware and stress results. Count auth/setup separately and test it too. A large fixture can run locally or under the existing scale gate. Reuse small statement-budget fixtures in PR tests and add no mandatory suite.

**Before 0.9.0, catalog correctness.** A single-project stress case with 5,000 pipelines
and 50,000 SQL tasks fails catalog generation in `lineage_cache_edges.sql`. The query expands
two bind variables per task/hash pair and the test Python's SQLite allows 32,766 variables.
`engine/repository/lineage.py` owns the read. Keep authorization and type/hash matching intact
and bound the bind set in the dialect read, starting with batches of at most 400 pairs and
leaving headroom for other filters. Include the failed-task exclusion in the bound strategy.
If a typed set join in PostgreSQL or staged SQLite join beats batching in measured plans, use it
without introducing a durable table. Preserve order across batches and publish only a complete
generation. An error names the project and failing read and tells the operator to retry after
resolving the error. Size: one PR, repository/query changes only, existing UI/CLI, no baseline
schema edit. Budget one bounded read per batch and no per-task SQL on a warm build. Test empty
and partial batches, exclusions, deterministic order and a fixture with an intentionally lowered
SQLite bind limit. Run the 50,000-task reproduction separately from mandatory CI.

**After 0.9.0, placed after 1.0.0 if needed.** A completed-run summary would benefit daily analysts only if repeated multi-task reads dominate after bounded/indexed queries. Prototype a single keyed row per run with last finalized revision, counts with completeness flags and duration. Populate atomically with finalization and make replay/idempotence explicit. A reopened run uses live audit state, and the next terminal revision replaces the stale projection atomically. Backfill bounded batches and permit “Summary unavailable” while it catches up. Avoid a duplicate summary for run fields already in `AUD_PIPELINES_RUN_LOG`. Size: up to two PRs for both schemas, query/API consumers and measurement, with an existing suite covering rollback, retry, reopen, older rows and retention. No new CLI or UI surface until a consumer demonstrates need.

**Latest-only definition document.** Do not adopt a giant browser document or use latest definitions for historical runs. It would invalidate on unrelated changes, increases the authorization surface, and omits historical pins. The catalog scale check below supports eliminating unnecessary history work before changing delivery format. If a definition-only cold/warm comparison shows improved parse time and transferred bytes, try private conditional GET on existing per-project or per-pipeline definition responses and bounded in-process reuse keyed by persisted version. Recheck permissions before returning a body or 304 and never share role-filtered responses in a public cache. Invalidate on a successful re-parse/deploy; report a failed parse with the exact version and preserve an explicitly identified previous good publication. Use a stored digest or stdlib hashing and a small bounded cache. Separate dynamic runs and immutable pinned definitions. Size if justified: one later PR, no table or command, HTTP headers and tests for revocation, reload, failed re-parse, historical links and multi-process invalidation. No core dependencies proposed.

## Other ETL capabilities

| Capability | Current coverage, operator need and disposition |
| --- | --- |
| Parameter files and run-time values | `operations/run_parameters.py` validates per-task overrides, snapshots admission and copies inputs for restart. `AUD_RUN_PARAMETER_OVERRIDES` already supports reproducibility. Reusable local files would help backfill operators with repeated multi-key runs. After 1.0.0, consider a CLI-only JSON file using stdlib, mapped into the existing request with no setting, table or server path. Refuse duplicates and unknown fields by key without echoing sensitive values. One PR, CLI/validation tests, same statement budget as inline admission. Reject mutable shared task variables and arbitrary connection or SQL overrides. |
| Restart and recovery | Covered by `operations/recovery.py`, `pipeline_resume.py` and existing recovery preview. Keep exact run and task scope; prefer bounded native task checkpoints where the handler already supports them. Reject a generic automatic restart from an arbitrary SQL statement after an unknown side effect. Suspend on error remains after 1.0.0. Branches finishing during suspension change completion rules, leases and consumption, for a benefit absent in the demo. A later design needs durable suspension, explicit resume, no reserved slots while waiting, branch-race tests, and current-state reads in one request. At least three PRs, both schemas, action/CLI/UI and state tests. |
| Target load order | `CFG_TASK_DEPENDENCY`, `CFG_PIPELINE_DEPENDENCY` and `handlers/sql/spec.py` support explicit parent-before-child and child-before-parent orders. Engineers declare those each topology change. Reject implicit FK-derived scheduling or constraint disabling. Publish clearer examples if parent/child order keeps recurring. |
| Lookups and error rows | Managed SELECT joins in `handlers/sql/spec.py` and warehouse-native indexes cover normal lookups; `handlers/sql/rejects.py` and `src/etl_craft/services/doctor.py` support rejects and retention checks. Keep source-side/warehouse plans in SQL. Reject a second generic lookup engine or row caches. A scoped reject drilldown could help data stewards weekly but is after 1.0.0 and requires a redaction/authorization policy. One request/≤2 data statements after scope, no raw-row access by default, one or two PRs for warehouse adapters, read API/UI and authorization tests. |
| Scheduling | The Scheduled and Paused pages, `operations/trigger_controls.py` and calendar history tables already represent schedule and operator controls. Schedule end date/count stays after 1.0.0 for finite migrations. Validate timezone and count rules at deploy, including whether manual starts/backfills consume quota. Size: two PRs, both schemas, config/CLI/API and schedule page, due-tick race and DST tests. |
| Reports and impact | The catalog, `operations/diagnostics.py`, `operations/config_files.py` and typed history already expose lineage and as-of evidence. After 1.0.0 add deploy impact and a reverse dependency report where regular schema changes require answering “who reads/writes this?” One scoped response with ≤3 batched statements, bounded depth/results and an explicit “lineage incomplete” outcome for undeclared Python/SQL dependencies. Two PRs, read API/CLI/catalog with tests for historical pins and authorization. |
| Promotion and definition comparison | `operations/bundles.py`, `operations/pipeline_reparse.py`, `operations/deploy.py` and typed history already cover package publication, parse versions and deployment. Keep promotion from reviewed code. Reject editable repository deployment groups. After 1.0.0 consider semantic diff of two explicit retained definitions for release reviewers, using existing versions. Refuse pruned versions; normalize for comparison while preserving dependency semantics. One request, ≤3 data reads, one to two PRs for API/CLI and catalog pane, mixed-version and redaction tests. |
| Named business events | Existing event/file evidence and start/run conditions cover known waits. A branch-published durable business event can matter if a file/partition is published before the entire branch finishes. Leave after 1.0.0 pending a real pipeline example. Same durable event identity on retry, no generic messages or payload exchange. At least two PRs for event schema/actions and UI, with duplicate/wake/timeout tests. |
| Test load and masking | Steward-controlled scratch validation and nonproduction masked copies are real periodic needs. Existing clone and validation are starting points, not substitutes. Both remain after 1.0.0. Require isolated scratch targets with explicit cleanup and no downstream publication; masking must fail closed for undeclared sensitive mappings. At least three PRs across handler/config, CLI/API and reports, warehouse contract and privacy tests. |

## Screens and walkthrough

Use the existing shell and back navigation. At both widths the same semantic components use the current theme tokens. Light uses light surfaces and dark text, dark uses dark surfaces and light text; the glyph and label survive color loss. Use blue for ▶ Running, amber only for ↻ Retry and ⚠ Warning, red for × Failed, green for ✓ Success, and neutral for ◷ Waiting and ‖ Paused. For an unavailable action the reason is in the shared hover tooltip, also reachable by focus and on touch via its trigger. Errors from submitted actions appear in the operation result.

```text
1440 px · light/dark                       390 px · light/dark
Operations | Monitor [all visible]         Monitor [all visible ▾]
           | Running Waiting Failed Late   [▶ Running] [◷ Waiting]
           | Project  Run  State  Evidence [× Failed] [Late]
           | sales    42   ◷ Pool 02:12    sales · #42 · ◷ Waiting
           | More results · as of 02:19    Pool heavy · since 02:12
                                           [Open run]    [More results]

Run #42 · × Failed      [Recover] [Copy ID] Run #42 · × Failed
Graph  List  Gantt  Events  Statistics     [Recover] [Copy ID]
┌ Selected task · Try 2 ──────────────────┐ Selected task · Try 2
│ × TARGET_WRITE · Merge   [First error]  │ × TARGET_WRITE · Merge
│ Read 800  Applied 790  Rejected 10      │ [First error] [Log]
│ 8 s · 100 rows/s · median 7 s (n=12)    │ Read 800 · Applied 790
│ Logs [Severity ▾] [Step ▾] [Download]   │ Rejected 10 · 8 s
└────────────────────────────────────────┘ Median 7 s (n=12)
Statistics: Task | Read | Applied | Time    [Statistics] [Logs]
Support: [Copy IDs] [Download] [Audit]      [Severity ▾] [Step ▾]
                                            [Support ▾]

Agents | Pool | Free | Heartbeat            Agents [Pool ▾]
▾ worker-2 / heavy / 1 of 4 / 02:19         ▾ worker-2 · heavy
  run #42 / try 2 / RSS 220 MiB / 0.5 CPU   1 of 4 free · 02:19
                                             #42 Try 2 · 220 MiB
```

On mobile the task detail takes the full content width and keeps the selected attempt and Back target. Sortable statistics use the existing compact row/card behavior. Logs keep a scroll region local to the stream. Support, audit and delivery open existing views with exact run scope. Later comparisons use two columns at 1440 and paired values per metric at 390, with persistent run IDs. Later trend charts have a numeric table in both themes.

- [Home, dark 1440](assets/monitoring/home-dark-1440.png) already places a failure in Needs attention, scoped to one project. At handoff the operator must repeat the scan across projects. Keep the analytics and link to Monitor.
- [Runs, light 390](assets/monitoring/runs-light-390.png) stacks correctly, but the failed card omits cause and waiting/late context. Reuse compact cards for incident evidence. The unlabeled visible project picker makes interpreting scope difficult on mobile.
- [Failed run, dark 390](assets/monitoring/failed-dark-390.png) already exposes Recover and Show task. First error navigation, metrics and a short handoff are absent from the first screen. Keep that recovery entry and make investigation available before graph traversal.
- [Pipeline, light 1440](assets/monitoring/pipeline-light-1440.png) has run grid, audit and an empty delivery panel. A locally seeded alert can be configured without a dispatched delivery. Tell the operator whether delivery evidence exists and offer the existing diagnostics.
- [Agents, light 1440](assets/monitoring/agents-light-1440.png) mentions agent-less deployments only after the instruction to start an agent. Make the active deployment model clear first.
- [Catalog, dark 390](assets/monitoring/catalog-dark-390.png) before building the catalog has an actionable rebuild instruction. After `generate-docs`, the CLI wrote 62 pages and reported two missing column-lineage inputs. Keep the remediation and surface incomplete lineage where users act on it.
- CLI `history --pipeline-code DEMO --all` found failed run 3 and successful run 4. `status --pipeline-code DEMO` refused with exit 9 and printed explicit candidates. Use `status --pipeline-code DEMO --run-id 3` in the Quick Start recovery example. This preserves exact selection. The first failed run and second successful run had different IDs. `doctor` returned 34 OK checks, no warnings or failures in this environment.

### Reference reading

PowerCenter 10.5.1 Workflow Basics, chapters 12–14 (monitor, task properties, performance and logs), Advanced Workflow (recovery and parameter files), and Repository Guide (object queries and deployment groups). Navigation and selected-run workflow references are [Airflow UI](https://airflow.apache.org/docs/apache-airflow/3.0.4/ui.html), [Jobs monitoring](https://docs.databricks.com/aws/en/jobs/monitor), and [Jobs recovery](https://docs.databricks.com/aws/en/jobs/repair-job-failures).

## Decisions

Implementation order is five S7.BB PRs after this planning PR, plus one S7.BC PR and one independent S7.BD PR. The
attempt schema changes and typed evidence are shared by the run detail and Agents.
Before 0.9.0, changes to attempt fields are baseline edits in both Engine DB schemas.
Later changes ship through both migration paths. The design needs no new CLI command,
core dependency, configuration knob or mandatory CI job. Existing command output and
API additions remain approval items.

Keep Monitor read-only. Use existing operations and access checks for actions, one component for each repeated element, stable scoped keyset ordering for lists, and existing pinned definitions for run evidence. Treat missing, zero and expired evidence separately. Keep cross-run search and trends out of the baseline implementation until the online read budgets are met. Prefer no core dependency, and no new CI job. Small checks belong in existing suites. Keep expensive seed and load evidence local and opt-in.

## Measurements appendix

Run from the baseline checkout with the repo virtual environment and Chromium installed. Keep logs and scratch projects outside the checkout, on disk.

```bash
export TMPDIR="$HOME/.cache/etl-craft-tmp"
mkdir -p "$TMPDIR"
systemd-run --user --scope --quiet make services-up > "$TMPDIR/services.log" 2>&1
systemd-run --user --scope --quiet .venv/bin/pytest -q -p no:cacheprovider \
  tests/integration/api/test_page_budgets.py \
  tests/integration/engine/test_catalog_scale.py > "$TMPDIR/budgets.log" 2>&1
```

Ten tests passed in 21.90 s. The tests assert observed counts against the checked-in budget. Grid compares 50 and 650 cells across 25 runs. Capabilities and project history compare 2 and 12 pipelines. These are service-operation counts with warmed operator context and include the operation's transaction work but exclude browser HTTP middleware.

| Operation | SQLite statements / transactions | PostgreSQL statements / transactions |
| --- | ---: | ---: |
| Pipeline grid | 15 / 5 | 20 / 5 |
| Pipeline capabilities | 18 / 4 | 22 / 4 |
| Project history | 14 / 5 | 19 / 5 |

The catalog fixture separately tests warmed statement-count equality between 100 and 1,000 tasks, and a 30-run display limit with 50-run history. Count equality does not establish bounded rows examined.

**Local catalog scale.** On SQLite, use `sqlite_engine_db`, `init_db` and `seed_catalog`
from the existing fixture setup. Under `acting_as(SYSTEM_ACTOR)`, seed 100 pipelines
(prefix SMALL), then add 400 (prefix LARGE), 10 tasks and 4 runs per pipeline. Time
`build_catalog(engine, config)` immediately after each population and count
`before_cursor_execute` events with SQLAlchemy, remove the listener, then execute and
fully fetch the checked-in `catalog_pipeline_runs` (project 1, limit 30) and
`pipeline_run_history` (pipeline ID 1, limit 50, no filters, expanding pipeline/status
binds). Record `time.perf_counter()` deltas. This is an in-process build including
first-time parse/cache population for new entities, without rendering or transport.

| Seed | Task definitions / task runs | Catalog statements / elapsed | Catalog run query | One pipeline history |
| --- | ---: | ---: | ---: | ---: |
| 100 pipelines | 1,000 / 4,000 | 6,049 / 5.782 s | 400 rows / 3 ms | 4 rows / 1 ms |
| 500 pipelines | 5,000 / 20,000 | 24,053 / 31.773 s | 2,000 rows / 12 ms | 4 rows / 1 ms |

For a repeated build call `build_catalog` before attaching the counter. The warm
runs measured 49 statements / 1.142 s at 100 pipelines and 53 / 8.609 s at 500.
Warm cursor counts moved little while elapsed time grew roughly with the task population.
This supports profiling the warmed build and reducing work before adding a browser cache.
The 500-pipeline
sample has one project, one timestamp and no attempt/log load. Timings are single
observations, not SLOs. The main finding is that publication can pay a large definition
and parse-population cost while browsing one run's bounded history avoids that work.
Keep parsed publication off the run-list request path. The experiment does not establish
that a browser document outperforms the existing HTTP/cache path.

Replacing the second seed increment with 4,900 gives 5,000 pipelines and 200,000 task-run
rows in one SQLite project. The second catalog build failed with “too many SQL variables”
in the expanded lineage tuple lookup. No end-to-end catalog timing or large-seed history
timing is reported from that attempt. The 50-project, two-year workload with concurrent
readers and writes remains a model. The single hot project tests a different boundary than
an evenly divided deployment, where each project would average 1,000 task definitions.

**Browser seed and method.** Copy `examples/demo` to a clean scratch directory, excluding existing databases, local logs, migrations, generated catalog and .env files. Set a scratch `XDG_CONFIG_HOME`. Run the Quick Start with the repo virtual environment and the local Mailpit. In order: `python prepare.py warehouse`, `etl-craft setup`, `etl-craft login`, `python prepare.py metadata`, then run SOURCE_A, SOURCE_B, DEMO (deliberate failure) and DEMO (success) with `etl-craft run --pipeline-code CODE --reason 'local monitoring study'`. Run the history/status and doctor commands above. Build the catalog only after capturing the empty state. Use the HTTPS loopback fixture pattern in `tests/browser/conftest.py` with `load_config` and `engine_db` pointing to the copied demo, and `open_page`/Playwright from `tests/browser/test_react_ui.py` with a fresh session per theme and viewport, at height 950. For each route attach a Playwright request listener, count URLs containing `/api/v1/` on a hard navigation through network idle, then take a screenshot and detach the listener. Counts exclude login, frontend bundles, catalog artifacts outside that API prefix and later polling. All four combinations returned the same counts and matched viewport width at document level. Captured 24 screenshots and retained six representative frames here. They do not prove absence of clipping inside panels or represent in-app navigation.

| Hard navigation after sign-in | Initial API requests | Page-specific calls apart from shell (two whoami, project-health and about) |
| --- | ---: | --- |
| `/ui/projects/default` | 6 | pipelines, insights |
| `/ui/projects/default/runs` | 6 | history, pipelines |
| `/ui/projects/default/pipelines/DEMO` | 8 | capabilities, pipeline detail, graph, history |
| `/ui/projects/default/runs/DEMO/3` | 7 | run detail, steps, status |
| `/ui/agents` | 5 | agents |
| `/ui/projects/default/catalog` before build | 6 | capabilities, catalog page |

A budget for one page feed does not eliminate shell calls or subsequent polling. Investigate duplicate identity and separate failed-run steps/status before adding separate feeds for new run statistics. Keep cache experiments separate from live request consolidation.

## Questions for the owner

1. **Monitor scope and placement.** A separate Operations destination keeps project analytics stable. Making Monitor the default landing page puts live incidents ahead of daily analytics. Recommend a separate destination, all authorized projects, 24-hour recent failures, seven-day maximum and 15-second visible polling. This blocks the navigation and feed contract, including cursor/filter defaults.
2. **Late means what?** Existing run SLA evidence gives a verifiable first view. Adding missed scheduled occurrences detects absent runs but also requires occurrence tracking and pause/timezone rules. Recommend active SLA and recorded breaches only. This blocks late filters, status labels and any new persisted deadline field.
3. **What should be recorded per attempt?** Persist typed first/last anchors plus peak RSS and CPU where supported, or show only current recorded outcomes and leave peaks missing. The first option improves overnight diagnosis and adds attempt columns/log envelope, sample age and API/CLI fields. Recommend it, with unknown metrics explicit and no sample-history table or dependency. This blocks schema, sampling and output changes.
4. **What occupies the first screen?** An inline failure/metrics summary supports immediate triage. A dedicated tab gives the graph more space but hides key evidence behind another action. Recommend the inline summary and a separate run Statistics tab, plus neutral wait marks and touch access to explanations. This blocks task/run layouts and status component changes.
5. **What should alerts and handoffs disclose?** Redacted identity, class, deadline and trusted deep link are actionable. Full logs and arbitrary template values add sensitive data and delivery variability. Recommend the compact payload, existing destinations, and a handoff using existing audit and download flows. This blocks the alert/output contract, required URL provenance and support UI. Keep automatic escalation deferred.
6. **When should log search and new storage ship?** Selected-stream filters solve the first incident step at limited cost. Cross-run code search and a summary table help broader investigations but add schema, retention and maintenance work. Recommend selected-stream only before 0.9.0 and retaining existing retention defaults. This blocks cross-run endpoints/indexes and any new retention setting or summary storage.
7. **How aggressively should definition responses be cached?** Keep current publication and measure, or authorize a private versioned conditional response experiment after baseline. Recommend a later experiment if it wins on bytes/time under permission checks, while retaining pinned definitions. This blocks browser cache semantics and HTTP contract changes.
8. **Which capabilities should move up?** Keep suspension, parameter files, impact, reject detail, schedule end, semantic compare and the other deferred capabilities after 1.0.0, or move an item up with a concrete production failure and an owner for its contract. Recommend retaining the current priority. This blocks implementing their state, settings, commands and schema.

9. **Which catalog size should the release guarantee?** Guarantee bounded catalog publication for a hot project, or document a project-size limit that requires teams to split definitions. Recommend bounded reads within the same project. This blocks the S7.BD acceptance envelope and any user-facing capacity limit.
