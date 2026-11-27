# Monitoring and operability for 0.9.0

Status: revised with both rounds of owner answers for PR #476. Tab-by-tab visual approval is pending. Evidence baseline: `c9f39e62`. Frequencies describe expected use at a site with hundreds of production loads.

At shift handoff an operator needs a list of incidents across authorized projects. During an incident they need the exact attempt, what reached the target, why the next task has not started, and what recovery will touch. During normal hours an engineer needs enough provenance to explain a change and enough bounded history to spot drift. Keep pipelines in code, execution order in dependency rows, and authorization and decisions in one operation shared by callers.

## Run, task and log evidence

**Before 0.9.0.** Every failed load creates triage work. The demo failed-run card already identifies `flaky_feed` and opens the task. `ui/src/pages/run.tsx`, `components/grid-task-details.tsx`, `components/run-overview.tsx` and `services/operations/run_log.py` already provide the run workspace, attempt context, links and lifecycle log. `task_run_facts.sql`, `operation_attempts.sql`, `AUD_TASK_RUN_LOG` and `AUD_TASK_ATTEMPTS` have counts, timings and failure classes. Preserve existing recovery and raw log downloads. Extend the same task panel and run workspace.

- Show the selected try and typed first and last errors captured per attempt: log line and step, error class, symbolic exit code name and failure class. Keep each attempt anchor stable across retries. Resolve it through the authorized log reader to the archived object when available, or say “Attempt 12 log was archived” when an exact line cannot be opened. Distinguish archive, expiry and read failure. Legacy attempts without a captured anchor show “First error was not recorded for attempt 12. Open the raw log for recorded detail.”
- Show only counts the handler produces, separating zero from absent evidence. Compute throughput only with a known numerator and positive duration. Use the task’s last 20 successful runs, ordered deterministically, as the median cohort. A missing metric contributes no sample. Display the sample size and show amber ▲ above 3× the median and amber ▼ below ⅓, with the multiple on hover or focus. No mark at the exact threshold. A zero median has no defined multiple. Do not report one for it.
- Run Statistics is sortable with one task per row, showing the final attempt and expandable previous tries. Keep applied counts and rejected counts separate. Avoid a cross-task “rows loaded” total that adds the same rows at successive stages. Cap a page at 100 rows. Keep task status and recovery independent of sort order.
- Keep raw and structured log views together. Structured events come from known execution points such as condition evaluations and statement boundaries. Record severity, step, timestamp, event code, attempt and sequence or byte anchor, with redacted fields. Legacy lines and arbitrary script output remain searchable in the selected raw stream with severity “Unknown”. First-error navigation opens the recorded event and can reset an excluding filter explicitly. Window and cursor apply to the selected stream, with 200 events per page. Expired lines show “Attempt 12 log expired on [date].” A storage outage says which stream failed and offers retry.

Use one run response for initial context and one selected-task response including statistics and failure, with at most two added set-based SQL statements per read above the separately captured baseline. Use one request per log window and at most two data statements after scope resolution. Prefer bounded typed events in the existing attempt log/spool and compact failure anchors on the attempt row in both schemas. Persist anchors with the terminal outcome, and derive the historical median only when a task is selected. Use plain offsets plus retention checks, with continuation after the same ordered event, including identical timestamps. No new CLI verb. Existing exact-run status/history/log surfaces can expose the data after output approval. Size: three implementation PRs for data, run/task UI and logs. Tests: empty versus zero, incompatible baseline, network/log loss, first error before terminal error, unknown severity, retry ordering, permissions, both schemas and breakpoint/theme checks.

## Waiting, agents and live incidents

**Before 0.9.0.** Operators check waiting work every shift and whenever throughput drops. `placement_wait_reasons.sql`, `AUD_GATE_WAITS`, `services/operations/agent_capacity.py`, `agent_reports.py`, `task_pauses.py` and `ui/src/pages/agents.tsx` distinguish capacity, leases and some wait causes. Reuse these decisions. A local controller without registered agents is a valid deployment. Add deployment-aware empty text and links to System health.

- Show why and since when for a recorded pool or connection wait, gate/event, retry delay, task pause or fence. Display deadline/next evaluation when recorded. A single run can have concurrent running and waiting tasks. Keep the run state and task wait distinct. “Placement reason unavailable. Last evaluated at 02:18 UTC” handles stale or missing evidence. Omit queue position because eligibility and competing claims can change. Never call a pause or wait “suspended.” Suspend on error is a separate deferred transition.
- Extend Agents with bounded current attempts, owner-verified PID/birth identity, pool, used/free eligible slots, last heartbeat and sample time. Linux alone exposes live interval CPU and RSS. macOS displays “Not sampled” for live telemetry. Completed attempts record peak RSS and user + system CPU seconds from the exact child’s `os.wait4(pid, ...)` result (stdlib), including waited-for descendants. Keep timeout/cancel polling with `WNOHANG`, set `Popen.returncode` from the waited status, and normalize `ru_maxrss` (KiB on Linux, bytes on macOS). Store unsupported values as NULL and display them as absent. Show CPU seconds divided by positive execution duration as average cores. Document that detached PYTHON tools are not included. Test concurrent children, genuine zero, unsupported values and both platform units.
- Add a separate Monitor destination under Operations. Project Home keeps its place and analytics and gains a compact failing/running/late/waiting strip linked to matching Monitor filters. Monitor covers all viewer-authorized projects and pipelines, and every row uses the shared S7.AN environment badge. Resolve visibility before counts, scheduling, paging and decoration. Never expose hidden totals. Default to active rows and failures ended in the last 24 hours, with seven days as the maximum terminal window.

**Late includes missing scheduled runs.** An operator needs to see a silent controller outage even when it produces zero failures. Derive due occurrences from definitions and run records without a new table. Use the same cron, timezone and calendar functions as `controller/schedules.py` and `engine/schedule_ticks.py`. Batch-load authorized schedules, calendars, pause and effective-date evidence. Intersect the recent lookback with the schedule's effective version boundary and start/resume boundaries. Exclude paused pipelines and holidays. A shifted business-day tick can qualify at its effective instant, once. Do not reuse the scheduler's last-run cursor to infer that earlier due occurrences ran. Read schedule change boundaries from `AUD_CFG_PIPELINES_HISTORY`, using applicable calendar and pause history when needed. Match by pipeline ID and exact UTC `schedule:` run key; manual runs and backfills cannot satisfy a tick. The fixed grace is the lesser of five minutes and the schedule interval, with no setting. Use the elapsed UTC interval between adjacent nominal cron ticks for that occurrence before applying calendar skips or shifts. After grace, an absent run appears as “Missed start.” If catch-up has queued it, update the same occurrence to “Queued late” until that run starts. A recorded final SKIPPED decision leaves the backlog and remains in history. Include overdue active SLAs and recorded breaches. When missed start and SLA facets overlap, count that row once in Late. Missing effective-date evidence shows “Schedule coverage unavailable” for the affected authorized pipeline rather than guessing.

Use one request per Monitor page or refresh, 50 rows ordered by bucket and stable timestamp/identity. Allow at most three data statements after scope resolution: bounded live/recent rows and facts, batch schedule/calendar/pause evidence, and matched run keys for the bounded candidate window. Prototype joining recorded keys by pipeline/time window or typed set, avoiding a bind per occurrence. Count exact authorized matches over the same bounded sources for the Home strip, without re-scanning on each chip. Keep older active rows reachable. If enumeration or a count exceeds the proven limit, reduce the explicit recent window and report its coverage. Never silently truncate a count. Poll the visible feed every 15 seconds and show last successful refresh after outage. A changed scope or invalid cursor returns “Filters changed. Start again from the first page.” Agent list stays one request with a pool cursor and one capped expansion, at most two added data statements per view. Size: one PR for waits/Agents and one for Monitor/Home/Late. Tests include no-run controller outage, queued and started catch-up, skip, pause, definition creation/edits, holiday shifts, grace/DST, lease transfer, range limits, visibility/revocation, counts and all four visual variants.

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

Surface an incident handoff in the existing run with redacted identifiers, failure class and symbolic error code, deadline, environment, and an authorized run link. Put the environment first in the alert subject, especially PROD. Reuse the existing server-configured public base where it resolves authorized UI links. Add no setting. Never derive it from request Host or forwarded headers. With no configured base omit the link, retain exact IDs, and have doctor report the missing configuration. Exclude row data, rendered SQL, parameter values and secrets from alerts and handoff. Keep existing admission, delivery dedupe and recipients. Link separately to existing scoped audit, delivery and download views. Document the controller listener’s internal `GET /health` (default port 8730) for external uptime monitoring. Connection refusal, timeout or a non-200 means the endpoint failed to answer healthy. A 200 on the controller listener establishes probe availability only. In split deployments the UI’s separate `GET /health` checks API/Engine DB readiness and can return 503 for connectivity, configuration or schema mismatch. An available UI does not establish controller leadership. Have doctor reuse the existing `AUD_CONTROLLERS` heartbeat freshness check (15-second writes, 60-second recent window) for the leader and report “No controller leader renewed in the last 60 seconds. Check the controller service.” Keep missed starts visible whenever the API and Engine DB are reachable. Use external monitoring for a full outage and introduce no paging channel. Keep doctor outside dashboard polling and measure support ZIP fan-out before changing it.

One PR, additive payload/UI changes and CLI/docs walkthrough, no table required. Reuse the selected run and existing alert/audit endpoints. No new read on initial load for collapsed support details. One bounded delivery/history read per opened panel with at most two data statements plus scope. Tests: viewer redaction, environment-first subject, missing configured base, forged Host/forwarding headers, absent/stale leadership and database failure, delivery dedupe/refusal, stale recovery preview, unavailable log, CLI explicit-selection walkthrough and keyboard/mobile recovery. Audit export, alert variables/attachments and recorded delivery escalation remain after 1.0.0. These matter to compliance and support during periodic reviews, but require a scope and retention contract. Initial export budget one cursor request and ≤3 data reads per 100 events with actor, before/after and UTC date. Test permissions and retention; estimate two later PRs.

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
SQLite bind limit. See the [S7.BD query inventory](road-to-1.0.0.md#s7bd-bounded-catalog-lineage-lookup).
The release gate exercises catalog, lineage, deploy, re-parse and validate at 5,000 pipelines
and 50,000 tasks in one project on SQLite and PostgreSQL, including enough recorded history
to stress trigger-link reads. This is a slow release check. Use only small bind-limit
regression cases in per-PR CI.

**Conditional 0.9.0 exception.** Defer summary storage by default. If large-model measurements show a page exceeds its budget after bounding and indexing, add a run-end summary for that page before 0.9.0 and include the before/after measurements in the implementation PR. Prototype a single keyed row per run with last finalized revision, counts with completeness flags and duration. Populate atomically with finalization and make replay/idempotence explicit. A reopened run uses live audit state, and the next terminal revision replaces the stale projection atomically. Backfill bounded batches and permit “Summary unavailable” while it catches up. Avoid a duplicate summary for run fields already in `AUD_PIPELINES_RUN_LOG`. Size: up to two PRs for both schemas, query/API consumers and measurement, with an existing suite covering rollback, retry, reopen, older rows and retention. No new CLI or UI surface until a consumer demonstrates need.

**Conditional latest-only definition cache.** Measure the present path first. If a definition-only comparison improves time and bytes, use `Cache-Control: private, no-cache` so reuse revalidates, with an ETag derived from the project metadata version and scoped representation. Deploy and re-parse must advance the version used by the validator. Check access and effective visibility before producing 304 or a body, so revocation takes effect on the next request. Keep only the latest cached version. This cache does not replace existing pinned historical run evidence. On failed publication, identify the version failure explicitly. Size if justified: one later PR, existing API, no table or CLI, tests for deploy, re-parse, account/role revocation, permission expansion, and historical run links.

## Other ETL capabilities

| Capability | Current coverage, operator need and disposition |
| --- | --- |
| Parameter files and run-time values | `operations/run_parameters.py` validates per-task overrides, snapshots admission and copies inputs for restart. `AUD_RUN_PARAMETER_OVERRIDES` already supports reproducibility. Reusable local files would help backfill operators with repeated multi-key runs. After 1.0.0, consider a CLI-only JSON file using stdlib, mapped into the existing request with no setting, table or server path. Refuse duplicates and unknown fields by key without echoing sensitive values. One PR, CLI/validation tests, same statement budget as inline admission. Reject mutable shared task variables and arbitrary connection or SQL overrides. |
| Restart and recovery | Covered by `operations/recovery.py`, `pipeline_resume.py` and existing recovery preview. Keep exact run and task scope; prefer bounded native task checkpoints where the handler already supports them. Reject a generic automatic restart from an arbitrary SQL statement after an unknown side effect. Suspend on error remains after 1.0.0. Branches finishing during suspension change completion rules, leases and consumption, for a benefit absent in the demo. A later design needs durable suspension, explicit resume, no reserved slots while waiting, branch-race tests, and current-state reads in one request. At least three PRs, both schemas, action/CLI/UI and state tests. |
| Target load order | S7.BA derives task and pipeline edges from `RUN_CONDITION` and `START_CONDITION`; `handlers/sql/spec.py` supplies the SQL load semantics. Keep order in those rows and reject implicit FK-derived scheduling or constraint disabling. Publish clearer examples if parent/child order keeps recurring. |
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
Home [Failing · Running · Late · Waiting]  Home [Failing] [Running]
Operations | Monitor [all visible]         Monitor [all visible ▾]
           | Running Waiting Failed Late   [▶ Running] [◷ Waiting]
           | Project / Env  Run  State  Evidence [× Failed] [Late]
           | sales [PROD]  42   ◷ Pool 02:12    sales [PROD] · #42 · ◷ Waiting
           | More results · as of 02:19    Pool heavy · since 02:12
                                           [Open run]    [More results]

Run #42 · × Failed      [Recover] [Copy ID] Run #42 · × Failed
Graph  List  Gantt  Events  Statistics     [Recover] [Copy ID]
┌ Selected task · Try 2 ──────────────────┐ Selected task · Try 2
│ × HANDLER · Merge        [First error]  │ × HANDLER · Merge
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

- Home places a failure in Needs attention, scoped to one project; at handoff the operator must repeat the scan across projects. Keep the analytics and link to Monitor.
- Runs stacks correctly, but the failed card omits cause and waiting/late context. Reuse compact cards for incident evidence; the unlabeled mobile project picker makes scope difficult.
- The failed run exposes Recover and Show task, but first-error navigation, metrics and a short handoff are absent from the first screen.
- The pipeline page has run grid, audit and an empty delivery panel; tell the operator whether delivery evidence exists and offer diagnostics.
- Agents mentions agent-less deployments only after the instruction to start an agent; make the active deployment model clear first.
- Catalog before building has an actionable rebuild instruction; after generation it reported missing column-lineage inputs. Keep remediation and surface incomplete lineage where users act on it.
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

Keep Monitor read-only. Use existing operations and access checks for actions, one component for each repeated element, stable scoped keyset ordering for lists, and existing pinned definitions for run evidence. Treat missing, zero and expired evidence separately. Keep cross-run search and trends out of the baseline implementation until the online read budgets are met. Prefer no core dependency, and no new CI job. Small checks belong in existing suites. Run the 5,000-pipeline acceptance seed in the slow release gate. Keep supplementary performance experiments opt-in.

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

## Owner decisions

PR #476 records the owner’s answers. The pre-0.9.0 scope includes Monitor and the Home strip, missing scheduled occurrences and SLA evidence, typed attempt anchors and resource evidence, inline triage, selected-stream event filters, the redacted alert/handoff, and the bind-limit defect. Cross-run search and the other previously deferred capabilities stay deferred. Summary storage has a measured-budget exception only. A definition cache, if justified, is private, conditional and latest-only.

## Visual review

Screens are approved by the owner on the implementation PR that builds them: real pages with
seeded data at 1440 and 390 px, light and dark. The prototype is at commit `c3771533` on the
kept branch for reference. Nothing is stored in the repository.

Owner approval is recorded on each implementation PR; this planning PR stores no screenshots.

## Owner questions

1. **Error code contract (answered).** There is no etl-craft taxonomy in 0.9.0. Show the
   warehouse-native SQLSTATE or vendor code when the driver provides one; otherwise show the
   existing failure class. A closed code enum is post-1.0. No new code column or taxonomy is
   in this plan.

2. **Mapping (answered).** No monitoring tab. Use an **Open in catalog** link to the existing
   task mapping page; the review fixture contains no Mapping screen.

3. **Catalog release gate (answered).** Statement count must be fixed per query kind plus one
   statement per 400-name batch, proven at 500 and 5,000 pipelines. At 5,000 pipelines and
   50,000 tasks on SQLite and PostgreSQL: cold build ≤5 minutes, warm rebuild ≤60 seconds,
   and one-pipeline re-parse ≤10 seconds, all recorded in release evidence.
