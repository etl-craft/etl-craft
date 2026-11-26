# Handover for the next agent session

Written 2026-11-26 at the end of a long Claude Code session, so a fresh session can continue
without the old chat. Read this file, then `AGENTS.md`, then the roadmap item you are working on.
Part 1 is the live state; part 2 is the full agent memory (owner decisions and preferences),
copied verbatim. When a memory note and the code disagree, the code wins; check before acting.

## Part 1: live state

### Working pattern

- The owner relays Codex results and design notes. Claude writes Codex prompts and answers design
  notes, and builds directly when Codex is out of quota (it is, as of 2026-11-26).
- Package repo: this one. Demo repo: `../support-insights` (`etl-craft/support-insights`).
- Wait for long runs with one notifying call; never poll. After `gh pr merge --auto`, stop.
- Commits end with the `Claude-Session:` trailer only (no Co-Authored-By).
- **Git stash hazard (happened twice):** `git stash push <paths>` can fail or save nothing, and
  a following `git stash pop` then applies the OLD `stash@{0}`
  (`fix/ui-interaction-usability`, which must stay untouched). Never chain `stash push ...; stash
  pop`. To check that a test fails on main, copy main's files aside (`git archive HEAD src | tar
  -x -C <scratch>` and `PYTHONPATH=<scratch>/src`) instead.

### Open work, in order

1. **Branch `fix/engine-idle-agent-load` (pushed, commit `1b75da88`, no PR yet).**
   Contents: the idle notification storm fix, a cheap `agent health`, task-start log lines, the
   child logger name fix, and inline compact toolbar labels (UI alignment, owner screenshot of
   the log toolbar). Done: `make static`, `make docs`, unit and touched integration suites.
   Still to do:
   - the browser suite with screenshots
     (`ETL_CRAFT_UI_SCREENSHOTS=<dir> uv run pytest -q -n 4 tests/browser`). Review the toolbars,
     especially the Pool / Agent id text inputs inside compact labels (`inputClass` has `w-full`
     and may collapse inside a fit-width label);
   - `make ui-check` (vitest, lint, and a rebuild check of the shipped `spa/`);
   - open the PR with the body in [Appendix A](#appendix-a-drafted-pr-body) (fill in the browser
     line), then `gh pr merge --squash --auto`.
2. **After it merges, on the demo cluster (`../support-insights`):**
   - recreate the three notify triggers on the Engine DB as `FOR EACH ROW` (see `schema.sql`);
   - run `sh infra/bootstrap/update.sh ../etl-craft`;
   - run `kubectl apply -k infra/kubernetes`, which also restores the package probe that was
     hand-patched to a shell check;
   - recheck: the idle commit rate (it was 525/s), the gap from task start to its first log line
     (it was 60-110 s), live logs in the UI, and grid refresh without a reload.
   - Support Insights PR #34 (`update.sh` reads `ci/PACKAGE_COMMIT`) was on auto-merge.
     `ci/PACKAGE_COMMIT` is still `468cd019`; bump it with `build.sh` in the next demo PR.
3. **Next `docs(plan)` PR (one plan PR at a time):**
   - re-scope **S7.AX.3**: live log transport already works (chunks reach the Engine DB within
     ~1 s, the API serves them for live attempts, the UI refetches every 3 s); what remains is
     covered by item 1;
   - add the re-parse rename and the full-refresh-safe demo SQL slice (below) if they are not
     planned yet.
4. **S7.AX.4: task logs that explain a failure.** Add a context block (try, agent, connection,
   run date and parameters, watermark window, non-secret task parameters), the rendered SQL per
   step with secrets masked, rule results with flagged keys (capped), the reserved ROW_ID range
   and an outcome block. On failure, add the error, the failing statement, its class and the
   remedy. Defect to fix there: the SQL log line doubles the catalog
   (`warehouse.warehouse.pre_ods...`).
5. **Verify a possible false FAILURE alert email** from a manual, non-failed alert run (seen on
   `SI_STEWARD_DS_AGENTS`).
6. **Re-parse rename (owner decision):** the definition refresh becomes "re-parse" (Airflow
   style): `pipelines re-parse`, and "Re-parse pipeline" / "Re-parse all" in the UI. "Refresh"
   means data only (`REFRESH_TYPE`, `--full-refresh`). No alias before 0.9.0. Ask the owner
   before renaming `lineage --refresh`. The order is a plan PR, then the package PR, then a demo
   follow-up.
7. **Full-refresh-safe demo SQL (owner decision):** demo SQL uses `$$pipeline_run_id_filter`
   (1=1 on a full refresh), never `pipeline_run_id = $$pipeline_run_id`. 12 demo scripts are
   hard-coded. A full refresh rebuilds from PRS history and never depends on expiring sources.
8. **S7.AY: ROW_IDs derived from the task run** (`TASK_RUN_ID*2^32+row`). It replaces the stored
   high-water mark (`AUD_TARGET_ROW_IDS`), which the owner judged a bad idea. Plan PR #459 is
   merged.
9. **Cloud suite:** add optional `ETL_CRAFT_TEST_SNOWFLAKE_EXTERNAL_VOLUME`, passed as
   `EXTERNAL_VOLUME` + `BASE_LOCATION`. The suite still hard-codes `SNOWFLAKE_MANAGED`, which the
   current trial account (GCP me-central2) lacks. Volume `ETL_CRAFT_ICEBERG` (GCS bucket
   `vcg-etl-craft-test`) works. `.env` already has the variable.
10. **Then:** S8.E, S8.F, S8.G, S8.H (+REJECT_LIMIT in the demo) and S8.A acceptance.
    Backlog: #440 leftovers (the Accounts header at 390 px, ActionButton mapping), deploy
    ~156 s perf, the per-run business-key reject undercount (a known limit), and Snowflake
    Postgres for 0.9.0 evidence (needs a new account).

### Findings from 2026-11-26 (demo cluster, package `a0e08c64`)

- **Notification storm.** An idle claim (`agent_claims.claim` → `claim_once`) ran
  `record_wait_reasons`, whose zero-row UPDATE fired the statement-level
  `trg_notify_aud_task_attempts`. That woke every claim long-poll, and each one repeated the
  update. Measured: 525 commits/s and 78 notifications/s with nothing queued, UI pods ~1 core
  each, Engine DB 0.8 core. Fixed on the branch above.
- **`etl-craft agent health`** took 2.1 s of CPU (it imported the whole CLI). With 11 agents ×
  liveness + readiness every 10 s, that was about 4-5 cores on a 12-core host, near the 3 s probe
  timeout. Fixed on the branch.
- **Child logger.** `agent/child.py` runs as `python -m`, so its `getLogger(__name__)` was
  `__main__` and every line it logged was dropped, failure tracebacks included. Fixed on the
  branch.
- **Restart transient.** After `update.sh`, agents crash-looped for a few minutes. Killed pods'
  Engine DB sessions still counted in `AUD_CONNECTION_RESERVATIONS` (the UI refused at
  70/100 reserved), and agents exit on "GONE or missing" while the API is down. It recovered on
  its own; worth a look later.
- **Support Insights demo:**
  - k3d cluster `support-insights` with Engine DB pod `engine-1` (CNPG; database and schema
    both `etl_craft`).
  - Trino pod `trino-*`; query history: `system.runtime.queries`, `source` = the attempt tag.
  - `.state/si-cli.sh` runs the CLI against the cluster API; `.state/wait-run.sh` waits for a run.
  - Scheduled runs fire every 15 minutes.

### Design decisions this session (S7.AX, merged as #460, #461, #462)

- The pipeline page follows Airflow 3.4's layout:
  - grid: 20 px rows, 18 px cells, one scroll;
  - a split of 30/70 (graph 70/30) and 10 runs by default;
  - Grid / Gantt / Graph views on the left and a path row on top;
  - no pipeline-level Code tab: code is shown per task.
- Filters are Excel-style checklists. Task status uses the selected run, else the newest visible
  run. Run status is filtered by the server (`history.run_status`).
- The run page mixes in Databricks: it has a full-width page of its own
  (`/ui/projects/:p/runs/:pipeline/:runId`).
  - Rows: in, written and rejected as 3 columns.
  - Recover names: "Recover failed tasks" (RECOVER), "Recover from a task" (rerun with
    downstream) and "Rerun the whole run" (RESTART).
  - `dry_run` previews show Will run / Will skip / Depends on upstream.
  - The Events tab uses the existing coverage; there is no pipeline-level "queued" row.
- Gamma stays on MinIO bucket notifications with an EVENT_SQL wait; EVENT_FILE does not list
  buckets.
- Snowflake: test with a customer (external) Iceberg volume. The login user MCTECHIE has no
  network policy; the tests use the service user `ETL_CRAFT_TEST_SVC` with role `ETL_CRAFT_TEST`.

### Appendix A: drafted PR body

The drafted body for `fix/engine-idle-agent-load` is in
[handover-pr-idle-agent-load.md](handover-pr-idle-agent-load.md).

## Part 2: agent memory (verbatim)

### flag-judgment-calls-explicitly

*When translating ambiguous/conflicting source material into concrete code or schema in this repo, tag every judgment call inline instead of silently deciding*

When resolving ambiguity or conflicts in source material (pasted notes, verbal corrections, prior drafts) into concrete SQL/code, tag every place a real judgment call was made — using a small closed vocabulary of tags (deviation, addition and choice tags) — and roll them up into a summary block at the end of the artifact.

**Why:** `sql/schema.sql` in etl-craft demonstrates this pattern deliberately: every place the DDL differs from literally-pasted schema drafts, adds something not requested, or picks an implementation approach over what notes said ("WILL BE ENFORCED AS TRIGGER") is flagged inline and summarized at the file's end, explicitly so it can be challenged/signed-off rather than skimmed past. CLAUDE.md calls this out as something to read "before writing any code," not a one-off flourish — it's the project's working method for schema-first, sign-off-gated development.

**How to apply:** Any time I'm asked to write something (schema, code, config) against ambiguous, conflicting, or incompletely-specified requirements in this repo, don't just pick a reasonable interpretation and move on — mark it visibly (comment tag + closing summary) so the user can review and correct judgment calls without re-reading the whole diff line by line. This matters especially for [[etl-craft-schema-first-workflow]] since nothing downstream gets built until sign-off happens.

### critical-but-scoped-engineering

*Question requests and propose better designs rather than implementing blindly, but scope solutions to realistic data-engineering failure modes, not exhaustive edge cases*

Push back or propose alternatives when a request has a real design concern, instead of implementing it exactly as asked without comment — but don't let that turn into over-engineering for every hypothetical input. Solve for realistic, common data-engineering failure modes, not the full space of theoretical ones.

**Why:** Given verbatim after the user had to correct an over-engineered heuristic (`sql_actions.substitute_pipeline_id`'s auto-append-a-`WHERE`-when-none-exists case, plus its regex-based `WHERE` detector, which silently changed a SELECT's behavior in a way its own author couldn't see by reading it): "you should not just implement what I ask, I expect you to question the idea and come up with good ones. but that does not mean we should adress all the infinite possibilities. only the highly possible data engineering possibilities." The lesson cuts both ways — the original heuristic was *both* an unrequested addition *and* an attempt to guard against a fairly unlikely case (forgetting `$$pipeline_id` on a genuinely incremental source), which is exactly the kind of over-scoped defensiveness now being corrected.

**How to apply:** Before implementing a request in [[etl-craft-schema-first-workflow]] (or similar ambiguous/design-heavy work), ask whether there's a better approach or an adjacent real gap worth raising — e.g. proposing the `DELETE_FLAG` audit-column check on `DELETE_ROWS`'s soft-delete path as a natural extension of an explicit ask to check "scoped audit columns." State the proposed extension to the user rather than silently expanding scope. But cap that follow-on scope at concrete, common failure modes (a target predating a convention, a hand-edited table missing a column) rather than chasing every theoretical one — column-*type* drift (e.g. `ACTIVE_FLAG` typed `BOOLEAN` instead of `VARCHAR(1)`), not just column *presence*, was explicitly left unhandled as out of scope for this reason. When genuinely unsure whether a case counts as "highly possible" versus "infinite possibility," it's fine to name the limitation and move on rather than asking each time — matches this project's established practice of flagging remaining scope limits inline ([[flag-judgment-calls-explicitly]]) rather than silently deciding or silently over-building.

### midtask-scope-expansion

*User sends substantial scope-expanding follow-ups mid-turn while a feature is already being built; fold them into the same feature immediately rather than treating as a separate/future task*

When a large build is already underway and the user sends a new message that substantially expands the scope of the *specific piece currently being built* (not a new, separate request), treat it as an amendment to that in-progress work and fold it in immediately — redesign and rebuild the affected piece before moving on, rather than finishing the original narrower version first and queuing the expansion for later.

**Why:** In [[etl-craft-schema-first-workflow]], while `EMAIL_ALERT` + SMTP was being built (a fairly plain "send an email with substituted subject/body" design already coded and tested), the user sent a mid-turn follow-up: "email alert should be html with css. success, falire types. task parameters will have pipelines parameter, if it is all, send the status of all pipelines for its latest. if the pipeline name is mentioned, then that alone. can contain 1, some, all. ... then each pipeline should have collapsible arrow. any other template, team should use airflow." This substantially changed the feature (plain text → HTML+CSS, added a whole multi-pipeline status-digest mode) but was clearly meant to land in the same `email_alert.py` build, not as a follow-up ticket. It also included its own explicit scope cap ("any other template, team should use airflow") in the same breath — the user scopes generously but not infinitely, consistent with [[critical-but-scoped-engineering]].

**How to apply:** If a mid-build message reads as "also, X should actually work like Y" about the thing currently on the workbench, rewrite that thing now — don't finish the original plan and append a TODO. Re-run/extend the tests for the affected module rather than assuming the original tests still fully specify correct behavior. Watch for an explicit scope cap in the same message (here: "team should use airflow" for anything fancier) and honor it as a hard stop, not just a suggestion — the user pairs expansion with a boundary in the same message more often than not.


### feedback_decide_dont_block

*Prefers Claude to make the call and keep building rather than stacking up blocking design questions*

Make the call and keep building. Do not stack up blocking design questions —
"I don't want to keep running into walls" (after a third
consecutive AskUserQuestion on the same DuckDB concurrency thread).

**Why:** the user engages readily with design questions when they open new
scope, but a question per sub-decision turns one choice into a queue of them
and stalls delivery. A decision already given (e.g. "keep subprocesses, queue
everywhere") should be treated as settled and built, not reopened when a
related wrinkle appears.

**How to apply:** raise a genuine blocker once, briefly, with a
recommendation, then proceed on that recommendation unless told otherwise.
State assumptions inline in the work instead of asking. Correcting a factual
premise is still expected — see [[feedback_critical_scoped_engineering]] — but
do it in one pass and keep going rather than converting it into another
question. Keep flagging judgment calls inline per
[[feedback_flag_judgment_calls]]; those are records, not requests for a
decision.

### feedback-load-env-with-project-parser

*etl-craft .env values contain ';' (Databricks JDBC URLs); never `source` it in bash — load it with etl_craft.core.text.parse_env_file*

Load the repo's `.env` (cloud test credentials) with `etl_craft.core.text.parse_env_file`, never with bash `. ./.env` / `set -a; source .env`.

**Why:** the Databricks JDBC URL is unquoted and contains `;` (`...;transportMode=http;ssl=1;AuthMech=3;httpPath=...`); bash ends the assignment at the first `;`, so the URL looked like it had no httpPath. On 2026-09-24 this led to a wrong "your .env is missing httpPath" report and an unnecessary workaround; the user had to point out the URL was complete.

**How to apply:** for cloud runs, read `.env` in Python with the project parser and pass the values in the subprocess environment. Never print values; list names only.

### feedback-fail-loudly-with-debug-data

*A failure is not always bad — prefer letting the pipeline fail with rich debugging data over silently working around problems*

"A failure is not always bad, sometimes it is the right thing to let the pipeline fail and give good debugging data for developers." The user asked that this principle always guide design in etl-craft.

**Why:** Silent fallbacks, auto-healing or skipping hide real problems (bad metadata, broken connections, unexpected data) and make them harder to debug later. The user values clear failures with precise diagnostics over clever recovery.

**How to apply:** When choosing between tolerating or working around an anomaly and failing, fail by default. Make the failure message name the exact object (pipeline, task, file, parameter, SQL statement), the observed value, what was expected, and the remedy. Record it in the audit and log tables and the per-attempt log. Don't add fallbacks that guess at intent; recovery goes through the explicit retry and resume paths. It fits with [[feedback-critical-scoped-engineering]] and [[feedback-decide-dont-block]].

### feedback-take-control-only-of-sqlite

*etl-craft may create things only in SQLite (which it owns); on every other system it requires what it needs to already exist*

The engine may create and manage objects freely only in SQLite, because the system creates it. On every other system (PostgreSQL Engine DB, all warehouses) it should not take full control: schemas, databases and similar containers must already exist. The engine checks for them and fails with the remedy (for example the `CREATE SCHEMA` to run) rather than creating them.

**Why:** the user said "Sqlite is something the system creates, so it's fine to take control there. But for other systems, it is better not to take full control."

**How to apply:** don't add auto-create or bootstrap paths for non-SQLite containers. Tables are still created by the explicit actions (`CREATE_TABLE`, `SETUP_TABLE`), never implicitly. Follows [[feedback-fail-loudly-with-debug-data]].

### feedback-explicit-types-cast-not-guess

*A declared datatype means cast the value to it (like SQL CAST); never guess a type from the value*

When a value comes with a declared datatype (for example a script's offset), cast it to that datatype the way `CAST(value AS type)` works in SQL: `Offset("7", "NUMBER")` holds 7, and `Offset("abc", "NUMBER")` fails. Inferring a type when none is declared is the "implicit cast" the user rejects. The datatype must always be given, and values are stored as text beside it.

**Why:** the user corrected my over-strict reading ("I may have made a mistake. it should cast exactly to the type we store... think of like we do cast(value as type) in sql").

**How to apply:** require the declared type, cast to it, fail on uncastable values with the value and type named, and never infer. Follows [[feedback-fail-loudly-with-debug-data]].

### reference-ngrok-live-check

*How to run the live publish-docs check against the user's ngrok account, and what ngrok does not do*

The user's ngrok account (free plan) is in `.env`: `NGROK_AUTHTOKEN` (the token, unquoted) and
`NGROK_COMMAND_IN_RUN` (their whole `ngrok http --url=...` command in double quotes; the reserved
domain is parsed from `--url`). Load it with the project parser ([[load-env-with-project-parser]]).

- Only one endpoint per domain: if the user's own ngrok agent is running, a publish fails with
  ERR_NGROK_334; ask them to stop it (Ctrl-C) first.
- ngrok's error pages and messages contain the domain, and SDK errors quote the token: mask every
  printed line of a live script, not just the URL.
- ngrok's IP restriction options were silently ignored on this plan (verified 2026-09-25), which
  is why publish-docs enforces Allowed_ips itself from X-Forwarded-For.
- A new endpoint can answer ERR_NGROK_3200 ("offline") for a few seconds; retry before judging.
- Run with `uv run --with 'ngrok>=1.4'`; the SDK is an optional extra, not in the dev venv.

### project-etl-craft-rewrite-status

*etl-craft status 2026-10-11 — v0.3.0 released; S5.K rejects (#143) and config history (#144) merged; S5.L SQL watermarks next, then S5.M-N, S5.C; soak ends 10-17*

As of 2026-09-26: the rewrite shipped as **v0.1.0** (tag on the release-branch evidence commit, merged
to main with a merge commit so evidence stays on main's history; GitHub Release with wheel, sdist,
SHA256SUMS; docs 0.1 = latest). After release, K1 landed as four PRs (#64–#67): pause/resume and
`run --skip`, run dates and backfills, the append-only consumption log plus `Gate_wait_minutes`,
and catalog run history/KPIs. Engine DB changes after 0.1.0 go through ENGINE migrations
(0001–0003 so far) with an upgrade test from each released schema in `tests/fixtures/schemas/`.

**L1 is now the 1.0.0 gate (user, 2026-10-03):** after all 1.0 work and bug fixes, the Support-Insights
platform (github.com/venkatcg00/Supports-Insights-Docker) is rebuilt on etl-craft in that repo (branch
`etl-craft`): Airflow/PySpark replaced, metadata deployed by CI pipelines as project migrations, `lnd`->`prs`
is an SCD2 merge (user correction), and both Superset dashboards must work. 1.0.0 ships only when every
pipeline and dashboard chart works. Plan: "Release candidate" stage (S8.A-S8.G) in
docs/development/road-to-1.0.0.md.

**Why:** the plan in docs/development/rewrite-plan.md is otherwise complete.
**How to apply:** build L1 only after the 0.2-0.9 work (it uses 1.0 release candidates); unreleased changes sit under CHANGELOG `[Unreleased]`
for a future 0.2.0 (release evidence per release/README.md, cloud suites via
`scripts/acceptance_cloud.py --env-file .env --wheel ...`; run suites sequentially — parallel runs
and network blips caused spurious failures during 0.1.0).

**Status:** v0.3.0 RELEASED (tag on 404dc96, release/0.3.0 = cf35231 + version bump +
test fix 9517c30 + evidence; GitHub Release with wheel, sdist, SHA256SUMS; no pools). Merge-back PR #138
(chore/merge-release-0.3.0, pools entry kept under Unreleased) — merge with a MERGE COMMIT, not squash.
Dependabot #135-#137 merged. Local branches next: #139 feat/sql-create-view (gate+cloud done, demos running),
then feat/services-config-files, then feat/sql-sqlglot-analysis (stacked on views); roadmap rows use #PRNUM
placeholders. Then S5.C. 0.4.0 after the soak passes on 2026-10-17.
**Status:** all PRs through #142 are merged: merge-back #138, CREATE_VIEW with statement hash
(AUD_TARGET_VIEW_STATEMENT, migration 0019), CSV config files, sqlglot guard, and roadmap S5.K-S5.N
(rejects, watermarks, event waits, column lineage from declared sources). S5.K merged as #143
(REJECT_LIMIT, SKIP_REJECTS_OVER_LIMIT, <target>__rejects with audit columns, NOT NULL check,
REJECT_COUNT migration 0020). #144 config history: AUD_CFG_<table>_HISTORY per CFG_ table (SCD4: VALID_FROM/VALID_TO/
CURRENT_FLAG, closed once by the next version), AUD_METADATA_CHANGES is a view, config export
--as-of, rehash audited; S6.A retention keeps everything unless a period is set (user decision).
Next: S5.L SQL watermarks.
**How to apply:** read that section before starting work. User wants new plan items placed in dependency
order with the reason, not appended to whichever release. A ~9 h "slow test run" was the laptop
suspending, not the tests (~5 min) — run long suites under `systemd-inhibit --what=sleep`.

**2026-10-17:** main at 68cfda0. Merged #185 (S5.R item 6 helpers), #186 (0.4 gate met by soaked
0.3.0; no 0.4.0 cut, no further soak), #187 (AGENTS.md "Working efficiently" + pre-pr-checks
"Known environment failures"), #188 (S5.R item 4 enums/errors). S5.R remaining: items 1, 2, 5, 7, 8.
Status writes must stay in engine/transitions.py (test_no_direct_status_writes); it sits exactly
at its 950-line baseline, so any growth there needs a split (S5.R item 7 territory).

### project-etl-craft-1-0-direction

*etl-craft 1.0 target, revised by the user 2026-09-27: scheduler/overseer + worker cluster (any backend), ONE shared PostgreSQL Engine DB for all projects; supersedes the earlier one-host-per-project decision*

The user's 1.0 target, as revised on 2026-09-27 (this REPLACES the 2026-09-26 "one host + one Engine DB
per project, no worker fleet" decision; don't bring that back):

- A standalone ETL orchestrator ("Airflow plus dbt for ETL", without their breadth). Motto: "bare bones,
  but robust".
- Execution: a scheduler/overseer plus a cluster of workers. The core only knows it has clusters/pools to
  work with; the backend (Celery or anything else) is an implementation detail. The overseer gets a bigger
  configuration than any worker (Codex's review recorded the user's rule: scheduler RAM >= 1.5x a worker's).
  Workers either run Python ingestion scripts or wait on warehouse queries.
- ONE PostgreSQL Engine DB for all projects: tight, normalised tables and single-row reads/writes suit
  PostgreSQL. Multiple DBs are acceptable if there is a good reason, but single is the default. On
  Snowflake or Databricks deployments, use the platform's managed PostgreSQL (Snowflake Postgres,
  Databricks Lakebase) as the Engine DB and turn cloning off.
- Unchanged: authors write metadata, SQL and Python ingestion only (no authored DAGs, no macros, no
  connector library); Python ingestion scripts are the team's responsibility (a script may launch its own
  container), but the loader/contract/offsets/outcome recording are etl-craft's; generated YAML is the
  one-way interface to external orchestrators and an Airflow DAG factory reads only the YAML; CLI, API and
  UI share one service layer.

The build plan is in the repo at docs/development/road-to-1.0.0.md (merged in #75): releases
0.2.0 stabilize, 0.3 identity, 0.4 overseer, 0.5 cluster, 0.6 at load, 0.7-0.9 UI and finish, with
workstream ids S2.A..S7.J and Appendix A mapping defects B1-B65 and weaknesses W1-W14 to items. It
merged the three-pass Claude review (living doc
https://claude.ai/code/artifact/620425e0-a2cb-49ba-8f2c-f0ee65ccaacf) with a Codex review, whose
untracked reviews/ folder was deleted at the user's request.

**Why:** the user answered "give it a cluster ... a single postgres db should be great enough for all
projects ... for a snowflake or databricks scenario, it is better to use snowflake or databricks provided
postgres instance and turn off cloning".
**How to apply:** plan scale work as scheduler + worker pools + one shared Engine DB with project
namespaces; keep the core backend-agnostic. The user welcomes design challenges
([[critical-but-scoped-engineering]]); release state is in [[project-etl-craft-rewrite-status]].

### feedback-keep-branches

*Never delete git branches (local or remote) — merge PRs without --delete-branch*

Never delete branches, local or remote: merge with `gh pr merge N --squash` (no `--delete-branch`), and
don't prune or clean up old branches even when merged or stale.

**Why:** the user keeps every branch to show the work was done in phases (after I had been
merging with `--delete-branch`).
**How to apply:** every PR merge in etl-craft and elsewhere for this user. If a branch was deleted, it can
be restored from the PR's head commit (`refs/pull/N/head`); creating a `release/**` branch triggers the
release workflow, so check that before recreating one.

### etl-craft-plugin-evaluation

*Official Claude Code plugins weighed for etl-craft on 2026-10-09 — pyright-lsp and security-guidance not installed, with the measured reasons and what replaces them*

On 2026-10-09 the user asked for skills and plugins that help with etl-craft work. Evaluated from the
local copy of the claude-plugins-official marketplace (`~/.claude/plugins/marketplaces/`):

- **pyright-lsp**: needs a `pyright-langserver` binary (none installed; `uvx pyright@latest` works).
  Baseline over `tests/` and `integrations/`: 228 errors in 45 files, mostly
  reportOptionalMemberAccess and reportArgumentType, so every test edit would surface noise. It
  catches removed imports and attributes, but not `dataclasses.replace()` keywords — the two misses
  the S4.I.5 gate caught. Not installed.
- **security-guidance** (Anthropic-authored): an Opus diff review on every Stop, an agentic review on
  every commit/push, and a SessionStart pip install of claude_agent_sdk. The built-in `security-review`
  and `code-review` skills cover on-demand review. Not installed.
- github MCP, commit-commands, pr-review-toolkit, feature-dev, databricks and duckdb-skills overlap
  with the `gh` CLI and built-ins, or are niche.

For the web UI (S7.A, releases 0.7-0.9: Jinja2 + htmx + the catalog's CSS, no JS build, Playwright e2e
in CI): when S7.A starts, add the `playwright` MCP plugin (Microsoft, official marketplace; vet it first) to
open pages, drive htmx flows and take screenshots; use the built-in `dataviz` skill for status colours, the
runs grid and health tiles; write a `ui-page` project skill from the first page's real conventions. Skip
`frontend-design` (it pushes distinctive marketing aesthetics; an operator console reusing the catalog CSS
wants consistency and density), and React/TypeScript/Figma tooling (not this stack).

Built instead: project skills `pre-pr-checks` and `roadmap-item` in `.claude/skills/` (see
[[project-etl-craft-rewrite-status]]); actionlint runs as `uvx --from actionlint-py actionlint`.

On 2026-10-15 the user asked about five more (they named them approximately):
- **NVIDIA SkillSpector** ("specktor"): a static scanner for skills. The owner said not to add it
 . A one-off scan rated `fixing-accessibility` SAFE before it was vendored; HIGH findings on chisel and
  anti-slop were false positives.
- **ui-skills** (ibelick, MIT): vendored only `fixing-accessibility` (plain HTML, scanned SAFE).
  `baseline-ui` assumes React/Tailwind. `improve-ui` (read-only audit) is worth reconsidering at S7.A.
- **Reticle** (reticlehq): a dev SDK plus MCP server embedded in a web app for agent runtime perception.
  Nothing to embed it in until S7.A; weigh it against the playwright MCP then.
- **Chisel** (simota/agent-skills, MIT): turns vague prompt wording into checkable specs. It is tied to that
  repo's 90-agent hub (`_common`, Nexus, Oracle). Skipped: roadmap "Done when" rules already require
  checkable criteria.
- **anti-slop** (rand/cc-polymath, MIT): scored our README, Quick Start, guide and CHANGELOG 0/100. The code
  rules overlap ruff, the quality baseline and `make history`. Skipped.

On 2026-10-30 the owner asked for a UI/UX plugin: installed `frontend-design` (project scope,
`.claude/settings.json`); use only its critique loop, not its "distinctive aesthetic" push (Databricks
layout is approved). The playwright MCP needs Node/npx, which this machine lacks; render pages with
the repo's Python Playwright instead (a scratch test seeding pipelines and screenshotting light/dark
and 390 px) and review the PNGs before every S7.A PR (recorded in CLAUDE.md, PR #292).

Later on 2026-10-30, after the owner installed Node: Playwright MCP pinned in `.mcp.json`
(`@playwright/mcp@0.0.83`, headless, isolated); AccessLint skipped (its skills run `npx …@latest`
and its scanner can't sign in). Instead axe-core 4.14.0 (npm pack into scratch, sha256
20c09fe1…) is injected into a signed-in Python Playwright session with `bypass_csp=True`; first
scan found 4 rule failures, fixed to 0 (PR #292). Vercel web-interface-guidelines vendored as
`/web-design-guidelines`; repo names in SKILL.md must be links, not backticks (test_agent_docs).

**Why:** the decision rests on measured noise and overlap, so it need not be redone.
**How to apply:** don't repeat the evaluation unless the user asks. Revisit pyright-lsp if the test tree
becomes type-clean; security-guidance with `ENABLE_STOP_REVIEW=0` (commit/push reviews only) if the
user wants automatic reviews.

**2026-11-15:** ECC (Everything Claude Code, affaan-m/ECC, ~300 skills, 71 agents) considered and declined by the owner: "we will work with what we have". Reasons discussed: per-session context cost, unaudited hooks (supply chain), overlap with our own AGENTS.md-based skills. Do not re-propose; if needed later, vendor single skills at a pinned commit after reading them, as with fixing-accessibility.

### workstation-memory-limits

*The user's workstation has 14 GiB RAM; systemd-oomd killed Code OSS (and the cloud run inside it) on 2026-10-09 — run long suites one at a time, each in its own systemd scope*

The workstation has 14 GiB of RAM, usually shared with Firefox, the ChatGPT desktop app and other
Electron apps. On 2026-10-09 `systemd-oomd` killed the whole `app-code-oss` scope (537 processes)
during S4.I.5's Snowflake acceptance run, which had been started from the Claude extension, so the
run died at 17 of 22. The kernel then OOM-killed the Trino container (exit 137).

`/tmp` is a 7.5 GiB tmpfs, so it lives in RAM. On 2026-10-10 it filled up: 4.1 GiB of pytest temp dirs
(wheel-demo venvs) plus about 3 GiB of scratch venvs. That made the 0.3.0 cloud evidence fail with ENOSPC
and squeezed memory.

**Why:** anything launched from the editor shares its cgroup and dies when oomd kills the editor.
**How to apply:** run long suites with `TMPDIR=$HOME/.cache/etl-craft-tmp` so pytest's temp dirs go to
disk; keep worktrees and scratch venvs off `/tmp`; clear `/tmp/pytest-of-venkatcg` when no pytest is
running; in a git worktree, copy `.certs/` from the main checkout before service suites (the TLS
containers trust those exact generated certificates). Run local suites one at a time, not the gate alongside wheel demos or cloud runs.
Launch long runs with `systemd-run --user --scope --quiet -- systemd-inhibit --what=sleep ...` (now in
the `pre-pr-checks` skill) so they survive an editor kill. If Trino is down, `make services-up` brings it
back before local warehouse tests.

After a reboot, the Iceberg REST fixture container can keep a stuck SQLite catalog: every commit returns HTTP 500 `SQLITE_BUSY` (main fails the same way), and `docker restart` does not help. Recreate it: `docker compose up -d --force-recreate --no-deps iceberg-rest` (safe during the soak, which uses DuckDB and Mailpit only). Seen 2026-10-11.

**Swap and the demo server.** This workstation is also the "laptop server" that hosts the S8 demo cluster and its self-hosted GitHub runner (owner). Swap already exists: 15 GiB zram (zstd, about 4:1, prio 100) plus a 16 GiB NVMe swapfile at /swap/swapfile (prio 10), with swappiness at 150. The owner wants the demo to use swap. Kubernetes pods get no swap by default (NoSwap sets memory.swap.max=0), so the k3d kubelet needs LimitedSwap, verified on a pod's cgroup. Idle demo services can swap out while suites run; still run one suite at a time.

### require-services-scope

*Never set ETL_CRAFT_REQUIRE_SERVICES=1 for unit tests, `make check` or the unit evidence suite — only for service suites; it broke runs three times on 2026-10-09/10*

`ETL_CRAFT_REQUIRE_SERVICES=1` turns service skips into failures. `tests/unit/test_services_fixture.py`
checks that a missing service *skips*, so the variable makes it fail. It also turns the cloud suites'
and wheel demos' by-design skips into failures in a whole `make check`.

It broke three runs: the S4.G gate run (66 false failures), the first Nightly workflow run (#130),
and the 0.3.0 unit evidence run.

**Why:** set broadly, it turns intended skips into failures, which then look like real ones.
**How to apply:** set it per command, only on the service suites (engine-*, warehouse-*, connections,
chaos, e2e, package and cloud) and on the wheel demos. Never on `unit`, `docs` or `make check`.
In loops over suites, put it on each service-suite command, not on the loop.

### soak-0-4

*The 0.4 gate's seven-day soak runs on the laptop as user service etl-craft-soak, 2026-10-10 08:01 UTC to 2026-10-17 08:01 UTC; how to check and finish it*

The 0.4 gate soak runs the demo under `etl-craft server` in `~/etl-craft-soak/0.4-candidate`. It
uses the 0.3.0 release wheel, built from `release/0.3.0` commit bbf2bdc, which is the code 0.4.0
certifies. `soak.py` (a copy of the harness, `scripts/soak.py`, on branch `test/soak-harness`) kills
the server every 20 to 180 minutes and checks every 30 minutes into `report.jsonl`. The final result
is `soak-result.json`, written at 2026-10-17 08:01 UTC.

- Status: `systemctl --user status etl-craft-soak`; log: `journalctl --user -u etl-craft-soak`.
- Check now: `~/etl-craft-soak/0.4-candidate/venv/bin/python ~/etl-craft-soak/0.4-candidate/soak.py check ~/etl-craft-soak/0.4-candidate`.
- If it stopped (reboot or logout), rerun the `run` command; it resumes until the same end:
  `S=~/etl-craft-soak/0.4-candidate; systemd-run --user --unit etl-craft-soak --description "etl-craft 0.4 seven-day soak" -- systemd-inhibit --what=sleep $S/venv/bin/python $S/soak.py run $S --days 7 --kill-minutes 20:180`,
  then `make services-up`. A reboot at 01:47 UTC 2026-10-11 was resumed within 4 minutes; the next check passed with no lost ticks.
- Don't run `make services-down` or `services-reset` while it runs: Mailpit receives the demo's alerts.

**Why:** 0.4.0 is tagged only after the soak passes.
**How to apply:** when it passes, record 0.4.0 evidence on the release line (all suites), add the
soak result to the CHANGELOG's Verified section, then tag and publish 0.4.0 like 0.3.0. If it fails,
fix the cause on `main`, cherry-pick the fix to the release line, and restart the soak.

**Outcome:** a reboot stopped the soak at about 05:09 UTC on 16 October, after
5 days 21 hours. The last check (04:59 UTC) passed with no problems: every due tick produced one
run (563, 564 and 564), 12,945 attempts succeeded (1 expected flaky-feed failure), and 88 kills
were recovered. No soak-result.json was written. The owner said not to restart it ("it is fine
if it has ended"), so record the 0.4 gate as an owner-accepted 5.9-day soak.

**Decision (owner, 2026-10-17): no 0.4.0 from this soak.** "Only soaked code should be correct."
The soaked wheel is 0.3.0 (bbf2bdc has the same src/ and lock as v0.3.0), so nothing is released;
main's changes stay under [Unreleased]. Owner, same day: "We don't need another soak": main's changes ship in the
next release without one. Recorded in docs(plan) #186. A local, unpushed `release/0.4.0` branch (version
bump only, from 134cbf6) exists; it is unused.

**How to apply:** never release code the soak did not run. Before cutting a release, check that
the soaked wheel's commit equals the release commit's src/ and lock file.

### authoring-no-dbt-jinja

*2026-10-10 — no dbt Jinja/model files; authoring is SQL files plus explicit metadata kept as versioned CSV config files (one per CFG_ table, ACTIVE_FLAG) that `etl-craft config apply` merges by key; CREATE_VIEW added*

Don't port dbt's Jinja, model-file format or `ref()`-inferred dependencies, and don't propose them as
the fix for authoring. etl-craft keeps its authoring model: one read-only SELECT per SQL task (inline or
in `sql_files/`), with pipelines, tasks, parameters and dependencies written explicitly as metadata.

**Why:** in the user's words, "a dbt guy who cannot write dependencies is something that won't happen.
Most teams would adopt csv configs anyway." Explicit dependencies are a feature, not a gap.
The user first said CSV loading was the dev teams' job, then reversed it the same day: "You need a
versionable config... Do merges based on table primary keys with csvs... they can just keep changing files
in repo and then those get updated in config tables", then "1 csv file for cfg table", and "inactive setup
as well through csv, flip flags using active flag". Built as `etl-craft config plan|apply|export`
(branch feat/services-config-files): files are the whole truth (absent active rows retire), ACTIVE_FLAG per
row, reactivation keeps ids, validate runs inside the apply transaction. Audit tables take no writes at all.
**How to apply:** CSV config files are the primary authoring path; project migrations are the alternative.
Treat views as the `CREATE_VIEW` SQL action (SECURE_VIEW parameter). Apply sqlglot analysis to SQL files as
well as inline SQL. When comparing etl-craft with Airflow + dbt, don't count missing Jinja or `ref()` as a gap.

**Scope clarified (owner, 2026-11-05):** "when I said jinja, it was about sql jinjas, not jinjas as a whole. I want sql to be deterministic as much as possible." The ban covers templating that generates SQL. Jinja for non-SQL output is fine: team-supplied HTML email templates (EMAIL_TEMPLATE, sandboxed with autoescape) were approved the same day.

### release-gate-no-skips

*The release gate refuses any skipped test; dialect-specific cases must not be collected where they don't apply (warehouses(...) on sql_world), or 0.x evidence must be re-recorded (cost ~2 h on 2026-10-10)*

`scripts/release_gate.py` fails a suite whose evidence has any skip, xfail or error. Six warehouse tests
added in S3.G skipped themselves on warehouses they don't apply to, so 0.3.0's first evidence (all
passing) failed the gate on four warehouse suites, and since evidence must come from the release commit
with only evidence/changelog changes after it, every suite (clouds included) had to be re-recorded after
the test fix (`warehouses(...)` in tests/fixtures/sql_warehouse.py, commit 9517c30 on release/0.3.0).

**Why:** a runtime `pytest.skip` looks harmless in PR CI but blocks a release.
**How to apply:** never add a runtime skip to a release suite for an inapplicable dialect or platform;
parametrize only the cases that apply. Run `make release-gate` on the first evidence before the long cloud
run, so a gate problem surfaces early.

### user-feedback-style

*The user finds criticism hard; raise problems as concrete fixes, and never bring up adoption, stars, marketing or "vibe coded" judgments about etl-craft*

The user said they are not good at handling criticism and feel defeated even by genuine
issues. etl-craft will be open source once published; they will talk about it publicly only once it
works correctly, so zero stars and no users are expected and do not matter yet. Contributors are welcome.

**How to apply:** do not assess the project's adoption chances, popularity, or how "vibe coded" it is,
and do not suggest promotion, PyPI marketing or re-prioritizing for adoption unless asked. When something
is wrong, state it as a specific fix with a plan (what breaks, the change, the check), not as a verdict on
the work. Keep being honest about real defects: [[fail-loudly-with-debug-data]] still applies.

### support-insights-final-emulation

*Support Insights runs only after every planned feature is built, as the final proof; its generators must deliberately emit realistic bad source data that etl-craft must handle*

User direction: the Support Insights rebuild (roadmap S8, the 1.0 gate) runs only after
everything planned is built, and must help find and fix issues rather than be a half-baked setup. The
final project must stand on its own. Its generators deliberately produce bad data the way real systems do,
and the emulation should cover most of what messy real-world sources cause (duplicates and replays, late
and out-of-order records, schema drift, bad values and encodings, orphan keys, hard deletes, empty or
truncated or spiking batches, outages and partial loads, timezone and DST issues, restatements); the
etl-craft-based system must handle each.

**Why:** it is the user's confidence test before talking about etl-craft publicly ([[user-feedback-style]]).
**How to apply:** do not propose running S8 early. Keep a catalog of source failure modes in the roadmap's
S8 section, each mapped to the etl-craft feature that handles it and the check that proves it, so features
still being built cover them; a failure mode with no handling feature is a roadmap gap to fill first.
Support Insights metadata should use configuration files (`etl-craft config apply`), not migrations.

2026-10-30: the owner also wants bad data that *fails* runs (not only absorbed rejects), so the demo
always shows failed/retried/blocked runs for real UI review; S8 now has a "Bad data that fails a run"
table (PR #293). The owner will judge the UI against the demo's real failures.

### etl-craft-purpose

*Why etl-craft exists — Informatica's operational basics (audit above all) for SQL warehouses, which Airflow + dbt setups lack; a lasting open-source tool, not a product or company*

The user: etl-craft will not be sold or turned into a company; it should be a good tool people
keep using, not a week of hype. The idea comes from Informatica and the basics it has that Airflow + dbt
setups lack: one tool instead of two, and above all audit tracking ("a must in any system"), which dbt
removes. Matching all of Informatica is not the target; its operational basics for SQL warehouses are.

The user sharpened this:
- **Orchestrator:** closest to Airflow plus PowerCenter's Workflow Manager and Workflow Monitor (PowerCenter-style operator actions, not constrained like Airflow).
- **Execution engine:** a better dbt. It handles ingestion too, and its predetermined action templates replace dbt's Jinja.
- **Documentation:** comes from metadata. Docs are given as task parameters and the docs build collects them. Column-level lineage, execution graphs, pipeline health, metadata views and a DAG dashboard come built in.
- **Transformation logic:** less transformation ownership than PowerCenter; the team writes the SQL and scripts.
- **Not** IICS (cloud SaaS). Self-hosted, one package.
- **Wording:** "not an Airflow-plus-dbt stack" means one tool covering what that stack does, not "unrelated to Airflow/dbt". Don't frame features as "Airflow-style" constraints; PowerCenter's operator behaviour is the reference.

**Scope (owner, 2026-10-28):** etl-craft is built exclusively for ETL/ELT data movement; it is not a
general-purpose orchestrator. Scheduling and run control exist to serve data movement. Python tasks
may call external tools (e.g. trigger an Informatica job), but data movement is the reason a pipeline
exists. Decline orchestrator features (XCom-style value passing, generic operators, arbitrary
workflows) unless the S8 demo shows a data-movement need. Example: no XCom; if a value must pass
between tasks, make ScriptResult.variables readable in the same run, size-capped.

**How to apply:** judge features by whether they make loads auditable and operations dependable (roadmap
rule 9: every load auditable from the Engine DB alone). Basics before scale: S5.K rejects, S5.L SQL
watermarks, S5.M event waits and S5.N schema-aware lineage come right after S5.B, before the worker cluster (S5.C).
See [[support-insights-final-emulation]] and [[user-feedback-style]].

### publish-after-1-0

*HARD RULE — etl-craft is not published (PyPI, announcements, posts) before 1.0; it is talked about only once results back it up*

The user: "It will only get published after 1.0, not before, that is a hard rule. We will
only talk about it when we have stuff to back it up." The repository being public on GitHub is not
publishing.

**How to apply:** do not propose PyPI uploads, launch posts, README marketing or adoption steps before
1.0, and do not add them to the roadmap unless asked. Keep the work on correctness and the 1.0 gate
([[support-insights-final-emulation]]). See [[user-feedback-style]].

**Release path (owner, 2026-10-27).** Keep following the roadmap. Then:
1. **0.9.0:** everything planned is complete.
2. **Owner's own audit:** the owner and the agents audit 0.9.0 themselves and fix what they find
   ([[project-usability-audit-deferred]]).
3. **1.0.0-alpha:** released to the public, asking people to use, test and break it. This is the
   first public release, the only exception to the hard rule above.
4. **1.0.0 stable:** made from what the alpha's users report.

**Superseded 2026-10-27:** the first public release is 0.9.0, a stable release (there is no
alpha); see [[project-release-0-9-public]]. Nothing is published before 0.9.0.

**Exception, 2026-11-03 (owner):** container images may be pushed to ghcr.io/etl-craft/etl-craft before 0.9.0, "when we have it complete" — i.e. once S7.F's images pass their smoke tests. Still gated: pushed only from the release workflow for a tagged candidate whose gate passed, never from untagged main; no `latest` before 0.9.0. PyPI and announcements still wait for 0.9.0.

### repos-stewardship-ui-direction

*2026-10-15 owner direction — three repos, package CI validates demo evidence only, stewardable pipelines with script FILE_VALIDATION, UI never edits metadata, team-owned CFG_ tables*

Owner direction on 2026-10-15, recorded in road-to-1.0.0.md (S5.V, S7.M, S7.O, S8) via PR #171:

- REVISED 2026-10-21: two repos — the package, and one Support Insights repo holding demo code, infra AND the etl-craft project (configs, SQL, scripts, seeds). Was three repos: the package; the demo; a config repo of CFG_ CSVs applied by CI
  (`config plan`/`apply`). A *very small* demo stays in the package (`examples/demo`, cut down)
  for CI tests; package CI never runs the Support Insights demo, only validates the results
  manifest it provides at release.
- The demo gets etl-craft from this repo's GitHub releases; PyPI only at 1.0.0 ([[publish-after-1-0]]).
- Stewardship: `CFG_PIPELINES.STEWARDABLE_FLAG`; one file per upload (pipe-delimited CSV/TXT or
  XLSX); no schedules, no manual runs (needs a file); steward picks pipeline from a drop-down.
  Explicit `FILE_VALIDATION` task = the team's own Python script, input params, no outputs; only
  allowed in stewardable pipelines. Blanket upload size in craft-connector.yml, per-pipeline
  limit in the validation task. Demo stewardship targets `dm` and `ds` tables.
- UI is never a metadata editor, in any scenario. Its *actions* match Informatica PowerCenter
  Workflow Monitor (start/stop any pipeline or task, run from task, recover, restart, hold, abort,
  override) — NOT constrained like Airflow. Plus run views, the generated catalog docs, run-health dashboards.
- Goal of 1.0.0: don't fail for obvious reasons — ride out ordinary outages (Engine DB restart,
  kills, blips) within a budget; catch ordinary mistakes before a run. Roadmap S7.P catalog.
- UI stack (S7.A, PR #174), "level 2": FastAPI + Jinja2 server pages in the `server` extra, vendored htmx + SSE,
  plain per-view JS modules (no build), plus a few pinned single-file vendored libs (e.g. Cytoscape.js for the
  Monitor DAG, charts). No Node anywhere. Django/Flask/React rejected. Docker Compose lives in the demo repo.
- Teams may add their own CFG_ tables (e.g. hashed passwords) maintained by their own scripts;
  etl-craft keeps no guards/contract/history on those.
- Target for complete PR CI is 10 minutes, not 5.

**Why:** owner wants a clean package/demo/config separation and a UI that is ops-only.
**How to apply:** design S7.M/S7.O/S5.V work to this; don't add UI metadata editing or engine
checks on team CFG_ tables; don't make package CI depend on the demo repo.

### choices-for-all-users

*Owner's personal preferences set defaults, not limits — keep configurable options other teams may want (e.g. Retry_on NONE/TRANSIENT/TRANSIENT_AND_UNKNOWN/ANY)*

When the owner dislikes a behaviour (e.g. "I hate it when the orchestrator restarts a failed SQL
transformation"), don't remove the option for everyone. Make the safe behaviour the default and
keep the other choices configurable. Their words: "this is for everyone, not just
me. if someone actually uses it is a different case."

**Why:** etl-craft is a tool for many teams; one person's taste shouldn't remove a choice
another team needs.
**How to apply:** when a preference conflicts with a capability, propose "safe default + explicit
setting" rather than deleting the capability. Example: S5.W `Retry_on` with values NONE,
TRANSIENT (default), TRANSIENT_AND_UNKNOWN and ANY. See [[decide-dont-block]].

### reuse-task-model

*Express new behaviour as ordinary tasks plus CFG_TASK_DEPENDENCY rows; don't invent hooks, per-task pre/post parameters or special execution paths*

When a feature can be modelled as ordinary tasks wired by normal dependencies, do that rather than
inventing a new mechanism. The owner, rejecting PRE_SQL_FILE/POST_SQL_FILE/PRE_SCRIPT
hooks: "Think of it like a normal task dependency in our architecture. It follows the same
dependency rules. We don't need to invent anything, just python tasks and sql tasks."

**Why:** one execution model keeps audit, retries, dependencies and UI behaviour uniform. Every
special path is more code, more docs and more failure modes.

**How to apply:**
- PowerCenter-style pre/post SQL and commands are upstream or downstream tasks.
- Decision tasks are tasks with typed edges.
- Reconciliation jobs are ordinary pipelines.
- Propose a new handler only when no existing task type can do the work, as with the unmanaged
  `SQL_SCRIPT`.

See [[choices-for-all-users]] and [[decide-dont-block]].

### perfect-not-breadth

*Perfect what etl-craft offers rather than adding breadth — no chasing databases, connectors or integrations; never Jinja/macros; don't compare against the union of many tools*

The owner: "Building 1000 things would be a waste. We should perfect what we offer."
They also said "We may not even see any adoption for a long time."

- **Comparisons.** Don't treat the union of many tools' features as one competitor's shortcomings.
  Compare against one tool at a time, and remember that no single open-source tool has all of it.
- **Databases.** PostgreSQL, Snowflake, Databricks and Trino are the targets. Rare databases get a
  generic pure-ANSI fallback, not new dialects.
- **No Jinja or macros, ever.** Reusable logic belongs in stored procedures called from tasks.
- **Interop by reading tables.** Teams read the Engine DB tables with ordinary tasks; don't build
  OpenLineage, Prometheus or similar exporters unless asked.

**Why:** a lasting, dependable tool for its real audience, not a feature checklist.
**How to apply:**
- Before proposing a new integration, ask whether an existing task type and the Engine DB tables
  already cover it.
- Prioritise correctness, robustness and polish of the existing features.

See [[reuse-task-model]] and [[etl-craft-purpose]].

### feedback-pre-1-0-breaks-ok

*Before 1.0.0, breaking API/JSON/CLI changes are fine when they move toward the 1.0.0 design; never keep a second version for compatibility*

Owner, 2026-10-18 (on #207 changing `GET /pipelines/{code}/runs` to the `history/1` document): "the final outcome of 1.0.0 is what matters in the end line."

**Why:** nothing is published before 1.0 ([[project-publish-after-1-0]]); only the owner's 0.3.0 soak deployment exists, and its upgrade path to 1.0.0 is the one compatibility promise. Keeping old shapes alive would recreate the duplicate implementations the one-implementation rule (AGENTS.md rule, enforced by lint-imports) removes.

**How to apply:** make the change, record it under CHANGELOG `[Unreleased]` → Changed, and mention it once in the PR; don't propose compatibility shims or dual endpoints, and don't stop to ask about pre-1.0 breaks. Engine DB upgrades from 0.3.0 still must work (migrations in both dialects).

**Updated 2026-10-27:** "pre-1.0" now means "before 0.9.0", the first public release. From 0.9.0, changes must be backward compatible and support rolling upgrades and rollback ([[project-release-0-9-public]]).

### feedback-cloud-one-try

*PR cloud acceptance gets one try; unavailable cloud capacity is recorded and does not block merge*

Owner 2026-10-19: if Snowflake/Databricks capacity is unavailable on the first try, that is fine — record it in the PR and the roadmap "Acceptance availability" note and merge (auto-merge). A cloud test that ran and failed still blocks. Release evidence still needs every cloud suite ([[release-gate-refuses-skips]]). Codified in AGENTS.md "Validation" and the pre-pr-checks / roadmap-item skills (PR #217).

**Why:** Databricks compute repeatedly unavailable held S5.O.3/S5.V PRs; owner wants a correct, consistent 1.0.0 without cloud availability gating every PR.

**How to apply:** one probe per affected cloud; never retry or wait; never treat a failing assertion as unavailability.

### project-standalone-no-airflow

*2026-10-19 owner dropped Airflow/remote mode; etl-craft is standalone; S5.AA is PR #221; S5.AB next*

Owner 2026-10-19: etl-craft is a standalone orchestrator from 1.0.0; Airflow support (generate-yml, etl-craft-airflow, remote mode) is deleted outright, no shims. Plan PR #218 adds S5.Y (two slices: export, then remote mode) and S5.AA (one action table for role/audit/placement/route, generated API routes, one request per action, then names/folders, then typed values), ordered before S5.X, S5.C and S7.A. Other agents may implement the slices. PR #220 (S5.Y.2) keeps Allow_schedule (per-env controller schedule off) and PIPELINE_PARAMETERS.TAGS, and plans S5.AB tags/filters, S5.AC RUN_PIPELINE trigger tasks (WAIT = controller holds wait, DETACH = agent confirms then ends), S5.AD per-pipeline permission groups (grants on pipeline or tag), S7.A.4 Databricks+PowerCenter navigation; order S5.AA → AB → AC → AD → S5.X/S5.C. 2026-10-20: S5.AA merged #221, S5.AB #222, S5.AC #223. Plan PR #224 adds S5.AE (one gateway): controller (one active, vertical scaling, --no-ui serves only /health), stateless `etl-craft ui` copies (2+), agents talk only to the API (no Engine DB creds); only controller + ui hold DB creds (owner chose two DB clients over one); [ui]/[all] extras replace [server]; --api replaces --controller; agent API built inside S5.C.

**Why:** the owner wants one source for every action across CLI, API and UI, and consistent names before 1.0.0.

**How to apply:** don't add Airflow/remote-mode code; new actions go through the S5.AA action table once it exists; the UI posts changes to /api/v1. Related: [[feedback-cloud-one-try]], [[project-etl-craft-1-0-direction]].

### feedback-one-pr

*Owner prefers one combined PR (code + plan changes) over separate PRs; \"multiple PR is time waste\*

Owner 2026-10-19: "add everything to 1 PR, multiple PR is time waste" — folded S5.Y.2 code plus S5.AB/AC/AD/S7.A.4 plan text into PR #220, overriding AGENTS.md's docs(plan)-only rule for that request.

**Why:** separate PRs each cost a CI cycle and review round for no benefit to the owner.

**How to apply:** when the owner adds plan/scope requests mid-item, put them in the in-flight PR and note the deviation in "Concerns and deviations"; don't split into a separate docs(plan) PR unless asked. Related: [[project-standalone-no-airflow]].

### feedback-no-reverse-engineering

*Other tools are behaviour references only; no code study, no warehouse/codebase import features*

Owner 2026-10-19: build features from other tools' documented behaviour (PowerCenter, Databricks, Airflow) without looking at their code. Do not plan "reverse engineer existing warehouse/codebase into metadata" importers.

**Why:** importers need access to codebases, warehouses and more, and are risky; studying others' code is unnecessary.

**How to apply:** cite documented behaviour as the reference in plans; never propose importers or code-level study. Related: [[feedback-perfect-not-breadth]].

### project-test-skills

*2026-10-20 owner: after Codex's S5.AD + plan-bundle PR, add six specific test skills and complete the testing suite before 1.0.0*

Skills shipped in PR #226; next is the gap audit + missing tests. Owner 2026-10-20: once Codex finishes S5.AD with the plan bundle (S5.AF indexes, S6.A/S6.B retention+archive gaps, S5.F run-pinned metadata, S7.A.4 new-tab rule), add test-expert skills in `.agents/skills/` (symlinked from `.claude/skills/`, shared by Claude and Codex) and then complete the testing suite with them before 1.0.0.

Skills agreed: test-etl-correctness, test-run-state, test-chaos-recovery, test-security, test-upgrades, test-failure-messages. Each is a repo-specific failure-mode checklist pointing at real code/fixtures, with an independent oracle per check and a mutation check proving the test fails without the change. UI browser testing waits for S7.A; query performance is S5.AF's guard.

**Why:** owner wants very specific skills, not broad ones that miss things.

**How to apply:** skills are a separate non-roadmap PR (not docs(plan)); build in a worktree if Codex is using the main checkout. Related: [[project-standalone-no-airflow]], [[feedback-one-pr]].

### project-demo-cluster-and-seeds

*2026-10-21 pending plan additions — S8.A laptop k3d demo of Support Insights and new S7.S seed tables; ride with the next in-order build*

Agreed 2026-10-21; now in road-to-1.0.0.md (S7.S row, S8 revisions) via #229. S5.X (#230) set naming: SCRIPT_FILE for every file a task runs (python_scripts/x.py, sql_scripts/x.sql, full project-relative paths), SELECT_QUERY for inline managed SELECTs.

- **S8.A laptop demo**: ports github.com/venkatcg00/Supports-Insights-Docker on k3d; one job per container; SQLite wherever possible except the Engine DB (CloudNativePG, 3 instances, 1 sync replica, PgBouncer for ui). Warehouse Trino over Iceberg (REST catalog on SQLite, minio-lake). Sources: Alpha MongoDB, Beta Kafka (apache/kafka), Gamma minio-gamma, one generator container. No Superset. Caps on generator, Kafka/Mongo/MinIO retention. Nightly iceberg-maintenance CronJob (Trino has no stored procs; script runs optimize/expire_snapshots/remove_orphan_files; min-retention 1d). Layers: LND/CDC overwrite, PRE_DM one table DELETE_ROWS+APPEND_TABLE per source, PRS/DM SCD2, DS SCD1, stewards upload to DM and DS. One demo repo (configs + code + infra, 2026-10-21); deploy workflow on push to main filtered to project/**, self-hosted runner with developer token only, push to main only.
- **S7.S Seed tables** (after S7.M): seeds/<catalog>/<schema>/<table>/ data.csv + columns.csv; `seed apply` replaces via CREATE_TABLE when content SHA-256 changed; once a stewardship upload ends SUCCESS the seed is locked forever, reports LOCKED and exits 0.

**Why:** owner decided both lock rules are standard behaviour, not settings: no unlock, and only a successful upload locks.
**How to apply:** include both blocks verbatim-in-spirit in the next Codex prompt; no setting to toggle either rule. Related: [[project-test-skills]], [[feedback-one-pr]].

**Revised 2026-10-22 (S8.B):** layers are LND overwrite → PRS SCD2 → CDC overwrite → PRE_ODS one shared table, each client DELETE_ROWS its rows then APPEND_TABLE → business rules → ODS SCD1, normalized (one table per entity) → DM SCD2, one flattened wide table. (Owner corrected an interim per-client overwrite back to the shared delete+append table.)
**Stewardship (S7.M, 2026-10-22):** every upload audited in AUD_UPLOADS (QUEUED status added); uploads during a running steward run queue and the next run takes all queued uploads in order; per-file validation; later upload wins via UPLOAD_ID dedupe order; each row attributed to its own uploader.

### project-1-0-gap-decisions

*2026-10-21 owner decisions on 1.0 scope gaps — added S7.T calendars, S7.U GDPR erasure, S7.V ALLOW_EMPTY, script secrets via providers, warehouse retention, upload archival; rejected list with reasons*

Agreed 2026-10-21; prompt given to Codex to add to the plan in the S5.C PR.

- **Added before 1.0:** S7.E script secrets (SECRETS param + task.secret via providers, no connections table, no encrypted Engine DB store); S6.A warehouse retention (__rejects, mirrors, Iceberg snapshots); S7.M upload archival (Uploads.Archive_to, audit row kept); S7.T business calendars; S7.U erasure register + ERASURE task (no suppression list; owner: "we don't control the source, keep deleting"); S7.V ALLOW_EMPTY default Y (empty overwrite is expected; demo DM is SCD2 so safe).
- **Rejected (Appendix B):** sample-data pipeline tests ("fixtures modelled to pass"), approval gates (overrides audited), row-drop checks (business rules), support bundle (owner: leaks confidential data outside), encrypted secret store, suppression list. Catch-up/backfill stay as built.

**Why:** owner wants 1.0 complete for the core job, not breadth; pushes back on features that add surface without solving a real failure.
**How to apply:** don't re-propose the rejected items; when proposing scope, check whether existing features already cover it and say honestly where the owner's call is wrong. Related: [[feedback-critical-scoped-engineering]], [[feedback-perfect-not-breadth]].

**Events and streams (later):** event waits are for discrete file/row triggers; cloud file arrivals use the cloud's own event + an external function writing a signal row (guide docs/guides/external-events.md: claim, delete on success, release on failure, park after 3 failed runs). No native bucket listing (S5.AG removed); Object_stores profiles moved into S5.F. Streams are read as scheduled micro-batches with per-partition offsets (S5.AH), never stream-triggered.

**UI and roles:** S7.A gains a command center (actions from the action table only, never a shell; no host or metadata actions; forms from request types with the CLI line shown; audited). S7.B gains IAM-like custom roles: `role` and `access grant/revoke/explain` commands + API + command center (not config files); bindings of account/group to role on deployment/pipeline/tag replace grants.csv and the account role column; built-in roles fixed; no self-escalation; last admin kept.

### project-endurance-run

*2026-10-21 owner replaced 1.0's 30-day soak (S7.I) with a 72-hour accelerated endurance run on the laptop k3d demo*

Owner 2026-10-21: "I dont even want a soak personally"; agreed to a 72-hour accelerated endurance run instead (S7.I rewritten in the S5.C PR, #231).

- One-minute schedules (about a month of runs in 72 h); agent kill every 6 h, controller every 24 h, one Engine DB failover, one 15-min warehouse outage, one candidate-to-candidate upgrade, S8.H failure scenarios once.
- Sample memory and connections every 10 min; fail if memory grows >10% or connections rise over the last 24 h; tick p95 < 1 s; Engine DB growth within S6.A budget.
- Rare events (DST, month end, holiday lists, token/cert expiry, retention) are explicit-time tests, not waiting.
- Only a fix to code the run exercises restarts it. The 200-active-runs tick check moved to S6.G's load benchmark.

**Why:** leaks and slowdowns scale with run count, not days; owner sees no value in a month of calendar time.
**How to apply:** don't plan or estimate a 30-day soak for 1.0; release evidence is the 72-hour run. Related: [[soak-0-4]] (the old 0.4 soak, finished).

### feedback-quietly-better

*Never claim etl-craft is better than another tool; be better silently, measured internally only*

etl-craft never claims to be better than any other application (Airflow, dbt, PowerCenter or
others), in docs, README, PR text or posts. It should simply be better.

**Why:** the owner: "We won't claim that we are better, we should silently be
better." Comparisons invite arguments; results speak.

**How to apply:** other tools are behaviour references only ([[feedback-no-reverse-engineering]]).
Performance targets (for example ready-to-claim latency) are internal test thresholds with no
comparison wording. When explaining design to the owner, a private comparison is fine; never
put one in project text. Related: [[project-publish-after-1-0]].

### feedback-competitor-features-not-goals

*Another tool's \"selling point\" is often what the owner finds annoying; never propose a feature because a competitor has it*

A feature another tool advertises (Airflow, dbt and the like) may be exactly the property the
owner finds annoying; etl-craft exists because those tools are annoying to use.

**Why:** the owner: "Something you feel like an advantage or selling point from a
competitor application would feel like an annoying property to me. That is the reason I wanted
to make this, like how dbt and airflow are very annoying."

**How to apply:** never justify or propose a design with "tool X has it" or "to match X". Start
from the problem a team actually hits and the simplest etl-craft-shaped answer. When another
tool's behaviour comes up, ask whether it is a pain point to avoid before treating it as a
gap. Related: [[feedback-quietly-better]], [[feedback-no-reverse-engineering]],
[[feedback-perfect-not-breadth]].

### feedback-ui-databricks-template

*Owner-approved UI direction: Databricks as the whole template, sign-in first, shaded light + dark theme, command console, notes out of the page*

The owner rejected text-like wireframes and minor restyles as "clunky"; the rebuild modelled on
the Databricks workspace was called "so much better" (PR #253, S7.A.0).

- Databricks is the whole template: top bar (project switcher, global search, theme switch,
  avatar), sidebar, Jobs-style pipeline pages (Runs/Matrix/Tasks/Permissions + details panel),
  job-run pages (top-to-bottom graph, timeline, list, task panel), Catalog Explorer for tables.
- PowerCenter still decides acting: select, then right-click menu / panel / header buttons.
- Sign-in page first. Light theme is shaded grey, never pure white; dark theme required.
- Command center is a CLI console (type `etl-craft` command lines, CLI output), not forms.
- Design annotations go in a closed drawer, never inline in the console.
- The page generator stays out of the repo; committed HTML is the design record.

**Why:** the owner judges UI by whether it looks like a real operator console, not by coverage.
**How to apply:** S7.A pages follow the approved wireframes; don't drift to generic or
modern-template styling. Owner 2026-10-30: where the generated catalog's existing UI (graphs,
search, table pages, gaps) looks better or is more useful than a wireframe, reuse and enhance
it instead of rebuilding to match the wireframe; one shared implementation, choice recorded. Related: [[project-repos-stewardship-ui]].

### project-ui-capability-gaps

*UI/admin plan written in PR #255: S7.Z governance+environments, S7.AA refresh, S7.AB standing controls, S7.A.5 matrix, S7.A.6 usability*

Owner 2026-10-25: S6 completes before S7.A. Before UI work, a docs(plan) update is pending, and
the owner will say when to do it. UI = Databricks layout + PowerCenter capabilities; no missed
buttons. The design-notes drawer and wireframe chip are wireframe-only, not the final UI.

Planned content:
1. A capability matrix in metadata-and-ui.md: every action-table action -> object -> UI place
   (header, right-click menu, panel, bulk bar, admin page) or console-only with a reason. An S7.A
   test generated from the action table fails when a non-host, non-agent action has no UI place.
2. Wireframe gaps to add: RELEASE, RESTART, RESUME, RUN_PAUSED, RECONCILE, watermark/offset reset,
   TRIGGER_PIPELINE; CONTROL_BULK multi-select; table Data tab (DATA_PROVENANCE/EDIT/UNLOCK);
   lineage refresh, generate docs, docs version, validate; admin accounts/groups/tokens/access;
   maintenance purge/rehash/upgrade-targets/clone; user menu (whoami, logout); task-run
   statistics (rows in/ins/upd/del/rej, throughput, SQL_SCRIPT statements); scheduled-runs view;
   system health (controller lease, Engine DB, warehouse, agents); held/paused view; runs filtered
   by agent/pool and failure class.
3. New features: a standing per-task pause (across runs, like pipeline pause) and a standing
   "treat task as SKIPPED/SUCCESS/FAILED" for downstream. Both live in an audited control store
   (actor, reason, optional expiry), never CFG_/config files, and take precedence in metadata
   views with an override badge. Proposed: an Active-overrides tile, config plan/apply notes,
   overridden SUCCESS = no data for HAS_DATA and no fresh output for consumers.

4. Usability rules, drawn from Airflow's UI failures: a failure summary
   first and jump-to-error in logs, never a bare "not found" (say pending, removed or unreadable);
   every action previews its exact scope, with no flag checkboxes like Airflow's Clear; selection
   is a click that stays, with sticky headers and full names; bounded paged reads and per-view
   performance budgets; why-waiting text and a plain one-line run summary; pause and resume are
   buttons that show the catch-up count; every time shows its timezone, and the run date is
   labelled apart from the start time; fan-out items shown by key; validation findings on the
   object. Also: search with shortcuts (`/`, Ctrl+K), pins, saved filters, bulk bar with
   per-object results; hide actions the role lacks, disable with a reason when the state forbids;
   undo-style opposites; requested/acknowledged/completed/refused; changed-since-opened warning;
   CLI line for every action; system-health and maintenance banners; inline help; personal
   settings limited to theme, timezone, default project, pins and filters; WCAG AA, keyboard only.

5. Direct SQL edits to package CFG_ tables in the Engine DB, in chosen environments (owner
   2026-10-25, for rapid testing; SQL first, UI editing later on the same switch if wanted). This
   is an exception to the AGENTS.md rule that the Engine DB refuses writes not made through
   etl-craft; update the rule. Design: a per-project switch stored in the Engine DB, off by
   default and off in production, set by an admin. When it is on, the actor-guard triggers allow
   CFG_ writes only (AUD_ and history stay locked), fill CREATED_BY/UPDATED_BY with `sql:<db
   user>` (SQLite: `sql:direct`) and UPDATED_DATE, and write the CFG history rows as config apply
   does. Edited rows are a candidate: pipeline refresh validates and activates them, and the last
   good version runs until then (check that S5.F admission already uses a validated snapshot; if
   not, include that). Drift: a "changed directly since last apply from files" badge, `config
   plan` lists the drift, and `config export` writes it back to CSV. Owner confirmed: Engine DB
   constraints still reject bad values immediately, and drift from files is an accepted cost of
   rapid development.
5b. Environments per project (owner 2026-10-25): many environments can share one Engine DB
   (S5.G), one project each. Add to CFG_PROJECTS: ENVIRONMENT_TYPE (enum DEV/SIT/UAT/PROD/SANDBOX/
   CUSTOM), an optional ENVIRONMENT_NAME label, and DIRECT_CONFIG_EDITS (Y/N), which is the
   per-project switch the triggers read. A check constraint forbids PROD with edits on.
   projects.csv is removed from the config files (owner): projects are admin work, managed by
   admin commands (add/set/list/disable, audited) and the admin pages. Pools move to admin as
   well (owner confirmed 2026-10-25). An existing projects.csv or pools.csv
   fails config plan with the remedy, like grants.csv. Developer files left: pipelines, tasks,
   task_parameters, task_dependencies, pipeline_dependencies, tables, columns, business_rules.
   Environments sharing one warehouse are not blocked; doctor and the admin page show an
   informational note only.
   S7.Y/S7.B access gets a project scope, so roles differ per environment. UI: an environment
   badge in the top bar and project switcher, prod clearly marked, and an environment filter.
6. Pipeline refresh, like Airflow's DAG parser but the pipeline never vanishes (owner: "very
   much needed"). One Refresh action per pipeline and per project re-reads metadata, SQL and
   scripts and runs validate, lineage and bundle checks. On errors the pipeline stays listed with
   an error badge and a broken graph (red nodes and edges; file, line and remedy). Proposed
   default: the last good version stays active and runnable, shown clearly; a per-pipeline option
   blocks it until fixed. The owner agreed to this default.

**Why:** the owner wants no missed buttons and PowerCenter-level control without config edits.
**Status:** written as PR #255 on 2026-10-25. DIRECT_CONFIG_EDITS was replaced by one `GOVERNANCE` column (STRICT/RELAXED; PROD must be STRICT) that also makes intervention reasons optional and typed confirmations plain (owner: "relax rules if the admin allows it, for everything").
**How to apply:** S7.A pages follow the matrix and rules in metadata-and-ui.md. Related: [[feedback-ui-databricks-template]].

### user-keep-git-simple

*Owner finds git worktrees confusing; use one folder and plain branches, and explain git steps simply*

The owner said they are a bit of a novice with git worktrees, which confuse them.
Don't create worktrees. Use the one project folder with plain branches. Before switching branches
there, check that Codex isn't working in it (or ask), and describe git steps in plain words.

### feedback-separate-admin-from-dev

*Admin work (projects, access, accounts, environments) never lives in developer config files; it uses admin commands and pages*

Owner 2026-10-25: "separate admin work from dev work." Config files hold only what developers
change about pipelines and data: pipelines, tasks, parameters, dependencies, tables, columns
and rules. Projects, environments, access grants, accounts, groups and tokens are admin work,
done through audited admin commands and admin pages, never through a config file a merged PR
could change. This removed grants.csv and projects.csv.

Don't block what teams can legitimately choose (for example several environments sharing one
warehouse); show an informational note and let them decide.

**Why:** a config-file PR must not be able to confer access or change environment safety.
**How to apply:** when adding a setting, ask whether a developer or an admin owns it; admin
settings get commands, not CSV columns. Related: [[project-ui-capability-gaps]].

### project-pending-plan-s6d-followups

*Next docs(plan) PR, written after Codex finishes S6.D: table-level BR, SCRIPT_KIND, ODS stewardship, S7.A.7 platform basics with owner decisions*

Owner 2026-10-26. One docs(plan) PR once Codex's S6.D is done (Codex uses the main folder):

1. Table-level business rules: `BUSINESS_RULE_LEVEL` ROW (default) / TABLE. A TABLE rule returns
   one row (`PASSED` Y/N, optional `OBSERVED`, `DETAIL`), stored on AUD_BUSINESS_RULES_RUN_LOG,
   no per-row results. REJECT fails the task, REPORT continues, INCOMPLETE refused. Owner: these
   checks are mostly counts, not granular.
2. Python `SCRIPT_KIND` INGESTION / UTILITY. UTILITY: no offset, row_count optional ("Not
   measured"). Existing tasks upgrade as INGESTION. SQL tasks need no kind: `$$watermark` declares
   it (SI_DM via S7.X). Offset panel/reset only on INGESTION Python and watermark SQL tasks.
3. Stewardship (S8.B/S8.F): DS steward = validate -> steward_to_lnd -> SCD1 into ds (unchanged).
   Business steward: SI_STEWARD_DM_FACT replaced by SI_STEWARD_BUSINESS through
   lnd-prs-cdc-pre_ods-rules-ods with source STEWARD; ODS SCD1 human writes under S5.O.3 locks;
   DM gets it via SI_DM, which lists the steward pipeline in WATERMARK_SOURCE_PIPELINES; DM has
   no human writes. Owner: "ODS by name means operational data store".
4. S7.A.7 Platform basics: forced change after admin reset, own password change (local only);
   generic sign-in error, "contact admin" text and admin sign-in notice; ACCOUNT LOCKOUT after
   repeated failures with admin unlock (owner: no growing delay, bad for devs); return-to page;
   expiry warning, cross-tab sign-out; cookie/CSRF/CSP/frame security; profile menu; error,
   empty, loading, reconnect, new-version states; tab titles; copy buttons; CSV export; `?`
   shortcuts; a11y basics; desktop-first, phone status readable; admin announcement banner;
   accounts page with last sign-in/failures/locks; About page. Personal settings stored
   SERVER-SIDE per account (owner). Out: personal subscriptions (owner: would need another
   email mechanism), avatars, self-registration, email resets, translations.

**Why:** owner wants every basic platform element accounted for before S7.A.
**Status:** written as PR #257 on 2026-10-26 (S7.AC, S7.AD, S7.A.7, S8 stewardship).
**How to apply:** build from the roadmap text. Related:
[[project-ui-capability-gaps]], [[user-keep-git-simple]].

### feedback-internal-deployment-threat-model

*etl-craft's UI/API usually sits on an internal network; don't weigh security trade-offs as if it were public-internet facing*

Owner 2026-10-26: the application is often not reachable by most people at all (internal
network, VPN); you may not even be able to open the URL. I had flagged "anyone who knows a
username can lock them out" as a drawback of account lockout; the owner corrected that this
assumes public exposure.

**Why:** realistic attackers are people already inside the network, which changes how much a
mitigation is worth.
**How to apply:** judge security trade-offs against an internal deployment by default. Keep the
real boundaries (roles, audit, cookie/CSRF basics, no secrets in output), but don't add
mitigations or caveats aimed at anonymous internet attackers unless a deployment mode exposes it.
Related: [[feedback-critical-scoped-engineering]].

### project-long-tests-after-demo

*Owner 2026-10-26: long-running validation (24h S6.G benchmark and similar) runs only after the S8 Support Insights demo completes without failures*

Owner 2026-10-26: "we can [run] all these kind of long tests after we complete the demo without
any failures". Build harnesses when their item comes up (S6.G benchmark), but defer the long runs
(24-hour reference benchmark and runs like it) until S8's demo passes cleanly.

**Why:** long runs are wasted while the demo can still expose failures that change the code.
**How to apply:** prompts and PRs deliver the harness plus a short smoke run and record the long
run as deferred until after S8. Likely covers S7.I's 72-hour endurance run too; confirm when
S7.I comes up. Related: [[project-endurance-run]], [[project-support-insights-final]].

### project-access-databricks-grants

*Owner 2026-10-26: S7.Y pipeline access follows Databricks job permissions (CAN_VIEW/CAN_RUN/CAN_MANAGE), principals group/role/account, delegated granting, no account rows in bulk file*

Owner 2026-10-26, folded into the S7.Y Codex prompt:
- Permission levels CAN_VIEW, CAN_RUN, CAN_MANAGE ("similar to databricks grants"); CAN_MANAGE
  may grant/revoke on that pipeline. Viewer/operator rows upgrade to CAN_VIEW/CAN_RUN.
- Principals: group, deployment role, or account. Bulk file (admin only) takes groups/roles;
  account-level rows fail there; account grants only via single CLI/UI command by an admin or
  CAN_MANAGE holder ("the giver should have access to grant a grant").
- grants.csv, projects.csv, pools.csv simply removed, no refusal message: only owner, Claude and
  Codex ever used them. Project/pool admin commands moved from S7.Z into S7.Y.

**Why:** access is identity, not metadata; pre-1.0 nobody else has the files.
**How to apply:** S7.Z then adds environment/governance columns to the project commands.
Related: [[feedback-separate-admin-from-dev]], [[project-ui-capability-gaps]].

Addendum, same day: project isolation. Owner: "one person should not have more projects access
than he should". Projects are securables like Databricks workspaces (project grants, default
deny across projects, pipelines without grants use the project level, upgrade adds role grants
so access is unchanged), no silent `default` project fallback, one folder per project in team
repos with explicit Orchestration.Project. Sent to Codex as an S7.Y addendum.

### project-config-files-are-helpers

*Owner 2026-10-26: config CSVs are change helpers, not source of truth; absence never retires, only ACTIVE_FLAG=N; partial deploys fine; many projects per instance OK (Airflow does it)*

Owner 2026-10-26: "config files are not the source of truth, they are just helpers." Deploy 10
pipelines once, later deploy files with only 1 new pipeline. Deleting rows/files deactivates
nothing; only ACTIVE_FLAG=N does. A truncated git diff deploys nothing extra. Planned as S7.AF
(prompt written; runs after S7.Y part A, before part B).

Also: multiple projects on one instance are fine ("airflow does that too"). Projects in an
instance share a trust boundary; don't propose per-project instances or a forced prod split
again. Isolation work stays at access/visibility (S7.Y part B) and accident prevention.

**Why:** the Engine DB is the source of truth (direct edits in S7.Z, admin commands for
projects/pools/access); files are a convenience for CI.
**How to apply:** never design features that infer intent from a row's absence in files.
Related: [[feedback-separate-admin-from-dev]], [[project-access-databricks-grants]].

Owner approved the S7.AF prompt with all risk fixes as plan text: S7.AG project migrations and
team tables confined to their project; S7.AH `etl-craft rename` keeping ids/offsets plus a
rename warning in plan; S7.Y part B deploy rights/cross-project CAN_VIEW/project log paths;
S7.AD SQL_SCRIPT and UTILITY default RETRY_ON=NONE; S7.A.7 locked admins don't block recovery.
Deploy overlap is a non-issue (one git diff = one set; duplicate keys rejected).

### project-noncore-security-fixes

*Owner 2026-10-27: merge gate and Actions tag pins are fine (solo dev); every other non-core audit finding must be fixed*

Owner 2026-10-27, after the non-core audit: "Merge gate is fine, i am the only dev on this
repo." GitHub Actions tag pinning is also fine for now. Don't raise either again.

Everything else must be fixed:
- agent tokens bound to a pool;
- the agent token kept out of task processes (per-attempt credential);
- SSO groups not frozen for Refresh_days;
- the ngrok catalog refused without allowed_ips;
- token default expiry plus LAST_USED_AT;
- sign-in scrypt outside the ACCOUNTS lock;
- OIDC clock leeway;
- OIDC discovery cached;
- upper bounds on core dependencies (sqlglot, sqlalchemy).

**How to apply:** put these into a Codex prompt (hardening item or Handover notes on S7.Y B and
S7.A.7). Related: [[project-config-files-are-helpers]], [[feedback-internal-deployment-threat-model]].

### project-usability-audit-deferred

*Owner 2026-10-27: rerun the product usability audit right before 1.0.0 and fix then; the 2026-10-27 findings are the starting list*

Owner 2026-10-27: "Maybe we should do this again right before 1.0.0 and then fix, doing
anything now may miss so many things we will build." Don't fix the usability findings now. Rerun
the full audit on the 0.9.0 candidate, once everything planned is complete, as a new user
would, plus context-free agents setting up from the docs only. Fix what it finds before 0.9.0
is published ([[project-release-0-9-public]]). F2 and A1 were pulled forward into S7.AI.

The 2026-10-27 audit used the 0.3.0 wheel, the demo, the CLI, the HTTP routes and catalog
screenshots. Its findings are the starting list for that audit; check each again:

**CLI**
- `logs` needs an attempt id that no command shows.
- `history`, `steps`, `status` and `explain` refuse when the run has ended. `history` without
  `--all` errors.
- `--run-id` also needs `--pipeline-code`.
- Selection errors say `pipeline_id=N` and suggest `--init-only` for reads.
- `status`: alphabetical order, 6-decimal durations, `SLA=MET` on FAILED, "blocked by
  failures: (none)".
- A failure summary has no next step.
- `explain` uses jargon (RETRY_ON, run_condition).
- `pipelines` has no last or next run, a blank PAUSED, SLA 0.0002h, and no `--all`.
- Tables are tab-separated with no alignment; `account list` has no header.
- `audit` is oldest first with no limit.
- INFO logs show by default (cgroup path, absolute log paths).
- `setup` without a TTY skips the admin and exits 0.
- A short password aborts the whole of setup.
- A wrong password says "ask an administrator" and gives no retry.
- `whoami` is unlabelled.
- The controller error doesn't name the token command. `token create` has no help and no
  "shown once" note.
- Users can't change their own password.
- The rerun hint omits `--with-downstream`; the 22 `run` options are ungrouped.
- 47 commands in one flat help list, with no typo suggestion.

**Server**
- The demo controller is silent about the API being off.
- `/` returns the stdlib 404 page.
- `--no-ui` help omits `/metrics`.

**Catalog**
- The DAG opens unfitted.
- "Repair: 100% of 1" hides failures.
- "Unchecked" repeats on every row.
- Absolute warehouse paths appear in pages.
- The home page has two search boxes.
- The mobile tasks table has gaps.
- The breadcrumb repeats "warehouse".
- The run page has duplicate "Used by" entries and alphabetical tasks.

**Docs**
- The README says "0.1.0 is the first release".
- The Quick Start uses migrations while the guides say config files.
- No troubleshooting page and no first-project guide.
- The roadmap is in the user navigation.

Still open for that audit:
- Should read-only views show the latest run?
- Is `--password-stdin` for setup acceptable?

**How to apply:** when 0.9.0 is complete, propose the audit as one item; don't fix these piecemeal
earlier. Non-core security fixes are separate and not deferred
([[project-noncore-security-fixes]]).

### project-release-0-9-public

*Owner 2026-10-27: everything planned for 1.0.0 ships as 0.9.0, the first public stable release; 1.0.0 follows real users' feedback; rolling-upgrade + rollback compatibility from 0.9.0*

Owner 2026-10-27: the whole 1.0.0 plan (checklist, S8 gate, long runs, cloud evidence) is now
**0.9.0**. 0.9.0 is the first public, stable release (PyPI, images, announcement); there is no
alpha. 1.0.0 comes later, shaped by feedback from real users.

Before 0.9.0 is published:
- the long runs (72h endurance, 24h benchmark) and cloud evidence pass;
- we audit it ourselves ([[project-usability-audit-deferred]]);
- context-free agents set up the service and get it working using only the published docs.

Pull forward now:
- F2: the catalog counts a failed-then-repaired run as 100% success;
- A1: `setup` without a TTY creates no admin and exits 0;
- the non-core security fixes ([[project-noncore-security-fixes]]).
These are planned as S7.AI.

Compatibility from 0.9.0 (owner chose "Rolling upgrade + rollback"):
- **Backward:** 1.x reads every 0.9 Engine DB, craft-connector.yml, config file, CLI invocation,
  JSON document and API v1 call. Removals wait for 2.0.
- **Mixed versions:** 0.9 and 1.x controller, UI copies, agents and CLI work together during a
  rolling upgrade. This drops the S7.F same-release rule; agents check a compatible range, not
  equality.
- **Rollback:** 1.x Engine DB migrations are additive only, so 0.9 binaries still run on an
  upgraded DB and a rollback is a reinstall.
- **1.x-only features:** a 1.x-only config column or setting fails on 0.9, naming the version
  it needs. Never ignore it silently.

**How to apply:** before 0.9.0, breaking changes are still fine ([[feedback-pre-1-0-breaks-ok]]
now means "before 0.9.0"). From 0.9.0, every change keeps these guarantees.

### feedback-next-prompt-assumes-merged

*Owner 2026-10-27: write the next Codex prompt as if the current PR has merged; fold leftover decisions from it into the next prompt, not a separate reply*

When asked for the next item's prompt, assume the current PR is merged (the owner pastes a
prompt only before starting new work). Decisions still open on the current PR go into the next
prompt as a "leftovers" part, not as a separate reply to paste into the old PR.

**Why:** the owner closes/merges the current PR before starting the next; a separate reply never
gets pasted.
**How to apply:** first section of the next prompt carries the leftovers (e.g. S7.Y B's catalog
sign-in moved to S7.A.7, carried in the S7.AI prompt).

### notify-dont-poll

*Every AI agent waits for long runs (tests, CI) with one blocking/notifying call, never by checking every few minutes; goes into AGENTS.md via the S7.AH prompt*

Owner, 2026-10-29: all AI agents (Codex, Claude, others) must wait for long test runs and CI with a
trigger or notifier — a background job whose completion notifies the agent, or one blocking command
(`gh run watch <id> --exit-status`, a foreground run with a long timeout, a bounded `until` loop
inside a single command) — not by re-checking a log, process or run every few minutes.

**Why:** each check re-sends the whole session; polling wastes time and tokens. The pre-pr-checks
skill already says "never poll", but agents still polled, so it must be in AGENTS.md.

**How to apply:** the S7.AH Codex prompt adds this rule to AGENTS.md (Validation) and to the
pre-pr-checks/roadmap-item skills. In my own work, use run_in_background / Monitor and wait for the
notice. Related: [[workstation-memory-limits]].

### project-name-stays

*2026-10-30 final: name stays etl-craft; owner is registering etl-craft domains*

Owner decided 2026-10-30, after reviewing alternatives (lodecraft, plyflow, tierwright), to keep
the name etl-craft and register the "etl-craft" domains. etlcraft.com is someone else's
"Launching Soon" placeholder; that does not matter for an open-source project.

**Why:** "Etl-craft should be fine enough"; "this is an opensource item either way".
**How to apply:** don't suggest renaming again unless a real data product appears under the name.
Icon chosen 2026-10-30 (option L): top plane M12 3 L20 7 L12 11 L4 7 Z in muted grey; stem M12 11 V21 and chevrons M6 12 L12 16 L18 12, M6 17 L12 21 L18 17 in accent blue; 24 viewBox, stroke 2, round caps.

### feedback-ui-status-colours

*Run-state colours follow operations convention; amber only for retries/warnings; professional over flashy*

Run states: green succeeded, red failed, blue running, grey queued/waiting (outlined), slate
skipped/cancelled/paused; amber (orange) only for retries and warnings (owner, 2026-10-30:
"orange is associated with retries… it can be simple, but it has to be professional and usable").

**Why:** amber for in-progress read as retrying; the owner wants a plain, professional console.
**How to apply:** use the `--run`/`--neutral`/`--ok`/`--bad`/`--warn` tokens in `core/static/catalog.css`;
check new colours with the dataviz skill's validator and 4.5:1 text contrast; every state keeps its
symbol and word (red/green fail protan separation). Render and review screenshots before UI PRs
([[etl-craft-plugin-evaluation]], [[feedback-ui-databricks-template]]).

### feedback-codeql-on-github

*CodeQL stays on GitHub only; don't add a local CodeQL step to pre-PR checks*

CodeQL runs only on GitHub; no local CodeQL in `/pre-pr-checks` (owner, 2026-10-30).

**Why:** owner declined the extra per-PR minutes and ~1 GB download.
**How to apply:** keep Semgrep MCP for local scans; when GitHub CodeQL flags a data-flow issue (exception text or cookies reaching a response), fix it on the PR. Before opening a PR, check by hand that exception text never reaches a response body, since Semgrep misses that flow. Related: [[feedback-internal-deployment-threat-model]].

### feedback-no-coauthor

*2026-10-30 owner: never add a Co-Authored-By Claude trailer to commits*

Don't add "Co-Authored-By: Claude ..." to commit messages on etl-craft (owner, 2026-10-30:
"dont add yourself as co-author").

**Why:** the owner's explicit instruction; it overrides the harness attribution reminder.
**How to apply:** omit the Co-Authored-By line in every commit; the Claude-Session line and the
PR-body footer were not mentioned, so keep them unless told otherwise.

### project-github-org

*Everything etl-craft lives in the etl-craft GitHub org; docs at docs.etl-craft.dev; security@etl-craft.dev receives only*

2026-11-01: the package moved to github.com/etl-craft/etl-craft (PR #306). Owner: everything related to etl-craft lives in the `etl-craft` org. That includes the Support Insights demo repository (S7.O), created there when S7.O starts, e.g. `etl-craft/support-insights`.
- 2026-11-03: created `etl-craft/support-insights` (public — owner: CI runs there, no need for private; empty). Owner chose a new repo over transferring `venkatcg00/Supports-Insights-Docker`: copy only what is needed (generators, generator UI/orchestrator, reference SQL as seed/view sources, LICENSE); not Airflow, PySpark, Superset, docker files or the JDBC jar. The old repo stays where it is.

- Domain etl-craft.dev is on Cloudflare. Docs go to docs.etl-craft.dev (CNAME and Pages custom domain not set yet). The apex home page and apex/www redirect wait for the 0.9.0 release (checklist PR #307).
- security@etl-craft.dev forwards to the owner's Gmail through Cloudflare Email Routing; it receives only, and the owner replies from personal mail. 2026-11-01: owner is trialling Zoho Mail on the domain; if it doesn't drop to the free plan after the trial, back to Cloudflare routing. Either way the address stays security@etl-craft.dev, so SECURITY.md needs no change.
- The owner's Gmail stays as the pyproject author email (owner is fine with that).
- 2026-11-03: the ghcr `etl-craft` package is public, so pushed candidate images are publicly pullable.

**Why:** one home for the project's repos, docs and contacts before the public release.
**How to apply:** new repos, images (ghcr.io/etl-craft/...) and links use the org; never a personal-account path. Related: [[project-release-0-9-public]], [[project-name-stays]].

### feedback-codex-builds-claude-architects

*Codex implements roadmap items; Claude is co-architect (prompts, design answers, reviews) and conserves quota*

2026-11-01, owner: "let codex do all the work for now. you are my co-architect kind, I cannot lose the quota quick."

**Why:** Claude's quota is the scarcer one; implementation burns it fast.
**How to apply:** don't take implementation work, don't create worktrees and branches, and don't offer to build items myself unless the owner asks or Codex is out of limit. Do: write Codex prompts, answer design notes paste-ready, assess plans, and do light checks (a few greps, not full test runs). Keep tool use minimal. Related: [[feedback-next-prompt-assumes-merged]], [[feedback-decide-dont-block]].

### feedback-no-ci-timing-parallel-clouds

*Codex prompts must say: don't time CI runs; run Snowflake and Databricks suites in parallel, not in sequence*

2026-11-03, owner: Codex was timing CI on every push and running Databricks and Snowflake one after the other. "CI timing is not needed. snowflake and databricks should run in parallel." Owner wants this stated explicitly in every next Codex prompt.

**Why:** both waste hours of wall time and quota; the cloud suites run on remote compute, so running them together costs little locally.
**How to apply:** in every Codex prompt's standard block:
- don't measure or report CI execution time, needs chains or queue time, and don't wait on CI to time it;
- start the Snowflake and Databricks suites at the same time as two background runs, each logged to its own file, and read both logs once.

My own prompts caused part of this (S7.AM slice 3: "measure the PR's longest needs chain"), so don't ask for timing. Related: [[feedback-notify-dont-poll]], [[feedback-cloud-one-try]], [[feedback-codex-builds-claude-architects]].

### feedback-s8-defects-one-pr

*Package defects found during an S8 demo item go on one package branch and one PR at the item's end; the demo builds images from that branch meanwhile*

2026-11-04, owner agreed: during S8.A Codex opened three separate package PRs (#319 python slots, #320 bytecode for probes, #321 controller Recreate), waiting for each merge to repin the demo. From now on every S8 prompt says: fix each defect on ONE package branch (`fix/s8<x>-defects`), build the demo images from that branch head and keep validating, open one package PR at the end of the item with every defect and its failing-first test, then pin the demo to the merged commit.

Owner: "this is the reason we had to make the demo, we have found stuff that we would not have found otherwise." The defects are the point of S8, never worked around in the demo.

**Why:** fewer PRs and no idle waits on merges ([[feedback-one-pr]]).
**How to apply:** put the block in every S8.x Codex prompt, alongside [[feedback-no-ci-timing-parallel-clouds]].

### project-samples-are-support-insights

*No bundled sample pipelines or load_examples in the package; the Support Insights demo repo is the sample setup*

2026-11-04, owner: asked for Airflow-style sample pipelines (pip install, open the UI, sample loads), then decided against it: "Airflow too has setup stuff to be done. We will provide a sample setup. The support insights demo alone should be enough."

**Why:** keeps the no-`init`, no-warehouse-in-core decisions intact; one demo, not two.
**How to apply:** don't propose bundled examples, `load_examples` flags or a demo command in the package. Sample experience = etl-craft/support-insights and its README; the package keeps only the small CI demo (S7.O). Related: [[project-demo-cluster-and-seeds]], [[feedback-perfect-not-breadth]].

### project-environment-context

*S7.AN "Always show the environment" — owner's top Airflow pain; CLI context line, PROD typed confirmation/--yes, alert subject, UI title; queued after S8.B + S7.E task secrets*

2026-11-04, owner: "airflow never tells you which environment you are in, and it is one of my biggest problems." The UI already had the header badge; the CLI and the alerts showed nothing.

S7.AN prompt given (owner sends it after S8.B's package PR and S7.E's task-secrets PR):
- a stderr context line on every project command, plus an `environment` field in JSON output;
- PROD write commands need the project code typed in an interactive terminal, or `--yes` (following pause's existing `--yes`); non-interactive runs without it are refused;
- login/whoami show the environment;
- alert subjects start with `[PRODUCTION]`;
- the UI `<title>` and the catalog header show it;
- UI parts (title, PROD dialog, "Recover run") moved to the React overhaul S7.AO on 2026-11-05.
S8.E's deploy.yml passes `--yes`.

**How to apply:** if S7.AN isn't merged when S8.E starts, remind the owner. In UI and CLI design, always show the environment. Related: [[project-ui-capability-gaps]], [[feedback-separate-admin-from-dev]].

### project-ui-overhaul-react

*2026-11-05 owner judged the Jinja/htmx UI unreleasable ("crude"); approved a React rebuild shipped prebuilt inside the wheel (Node only at our build time, never for users)*

2026-11-05: the owner looked at the S8 demo UI and called it "very crude… unreleasable". I took screenshots and agreed: browser-default controls, no hierarchy, clipped table actions, repeated labels.

Decision (owner): the Airflow/Dagster route.
- React + TypeScript + Vite, shadcn/ui (Radix + Tailwind), TanStack Query/Table, React Flow for DAGs.
- The app is built in CI/release, and the wheel and sdist ship the built static files; FastAPI serves them. Users never install Node: "node not being in users dependency to have is fine with me".
- The SPA talks only to /api/v1. Keep cookie session + CSRF, the approved Databricks-style layout ([[feedback-ui-databricks-template]]), the status colours ([[feedback-ui-status-colours]]) and the Playwright browser suite.
- Slice 1: the scaffold + Home, Pipeline runs, Run detail with its graph; the owner reviews screenshots before the remaining slices.

Order of the owner's 4 items: finish S8.B → S7.AN (CLI/alerts environment context; its UI parts and the "Recover run" button moved into the overhaul) → UI overhaul (S7.AO).

**2026-11-05 update (owner):** the new UI becomes the ONLY UI once polished (old Jinja/htmx pages are deleted in a final slice, new UI served at `/ui`); visual reference is Databricks. Slice 1 (`feat/ui-react-foundation`) serves at `/app`, built output committed under `src/etl_craft/api/spa/`, `make ui-check` job in CI; Codex out of weekly limit so Claude builds the slices.

**2026-11-05 logo:** the SPA header must use the approved mark (option L, `core/static/mark.html` / `favicon.svg`), now `ui/src/components/logo.tsx`; I had wrongly invented an "A" mark. Owner also said "we need a better logo" — any redesign belongs to roadmap S7.L; offer options, don't redesign inside a UI PR. `/api/v1` is for action routes only (a unit test enforces it): UI-only endpoints live under `/ui/...` and return JSON errors when the client asks for JSON.

### feedback-design-answers-add-tests

*The owner relays Codex design notes to me because I turn a decision into constraints plus concrete test cases, which the owner can't write directly*

2026-11-05, owner: "I can answer these myself, but I ask you because you add context and test cases for this, which i cannot do directly."

**Why:** the owner can choose an option; the value I add is the paste-ready rules: edge cases, failing-first tests, root-cause scope and what not to do.
**How to apply:** every answer to a Codex design note gives the choice (or a better third option), the constraints, a concrete test list, and the docs, regressions and Handover notes. Keep it short, without analysis essays. Related: [[feedback-codex-builds-claude-architects]].

### feedback-recommend-model

*Before each piece of work, tell the owner which Claude model to use (Haiku / Sonnet / Opus) for it*

2026-11-05, owner: "everytime, tell me right model to use in claude for something." Codex was out of weekly limit, so Claude does the building and quota matters.

Guide: Haiku = mechanical (run suites, read a CI log, small fixes, push/PR steps). Sonnet = default for implementation (features, S8 defects, React UI slices, multi-file changes). Opus = hard design notes, security-sensitive code, concurrency/lease/recovery bugs.

**Why:** conserve quota without losing quality where it matters.
**How to apply:** at the start of each new task or phase, add one line: "Model: <X> — <reason>". Related: [[feedback-codex-builds-claude-architects]].

### feedback-shared-ui-components

*UI work must use shared components from the start; never copy the same markup across pages*

2026-11-05, owner on the React UI: "you should have already thought of shared elements. you cannot just copy the same code everywhere and expect it to be the same after few iterations."

**Why:** hand-copied markup (sidebar, error notices, selects, headers, route strings) drifts apart over iterations; the owner expects one implementation per UI element, like the package's "one implementation per concern" rule.
**How to apply:** before building a page, list the elements it shares with other pages and put each in `ui/src/components` (common.tsx: Notice, Loading, PageHeader, Fact/FactList, SelectField, Eyebrow; sidebar.tsx; environment-badge.tsx) and addresses in `ui/src/lib/routes.ts`. `ui/eslint.config.js` forbids raw `<h1>`, `<select>`, `<dl>`, `role="alert"` and hand-built `/projects/` paths in `src/pages`. Add a new shared piece and a lint rule rather than a second copy. Related: [[project-ui-overhaul-react]].

### feedback-review-own-screenshots

*Before showing UI work, inspect every screenshot critically (both themes, phone width) and fix visible defects first*

2026-11-05, owner on the React UI: "a human engineer would have been so pissed off with my observations." They had to point out basics one by one: dark mode not dark, light sidebar missing, sidebar not full height, copied markup instead of shared components, project shown twice, invisible graph links, white controls in dark mode, weak font, tiny graph.

**Why:** the owner reviews by looking; every obvious defect they find that I could have seen costs them trust and time.
**How to apply:** after each UI change, open the screenshots in light, dark and 390 px and check every region (header, sidebar, tables, graph, controls, empty space, fonts, duplicated information, contrast) BEFORE reporting; test with data that exercises the feature (a pipeline WITH dependencies, a failed run, a long list), not only the easy case; then report only what is verified. Related: [[feedback-shared-ui-components]].

### project-2026-11-07-close

*State at end of 2026-11-07 session - PR #363 UI redesign, OSS study findings A-E scoped, tomorrow's items*

2026-11-07 close. PR #363 (feat/ui-airflow-workspace, last commit 4f2efa73) holds the UI redesign; the owner approved the redeployed demo ("looks good enough for now"). Auto-merge not enabled.

Evidence-based OSS study (Airflow, Dagster, Prefect, dbt, SQLMesh, dlt, catalogs) is closed. Scoped next, owner decides which get design notes:
A. correctness: validate lineage-reads vs dependency rows (warn first), refuse CREATE/OVERWRITE on a live SCD2 target, lease expiry on DB clock in renew/reconcile.
B. backfill flags (--dry-run, --only-missing), overdue-run metric, queue timeout.
C. before 0.9.0: compatibility page, Schema_version, rollback runbook, per-task Python env.
D. catalog: table owner, build diff, vanished-object guard.
E. watermark lookback (or document the pattern).

**Why:** owner stopped for the night, low usage.
**How to apply:** tomorrow first do the demo failure-alert rewiring (ALWAYS edges from leaf tasks + EMAIL_ON_STATUS), then remaining #363 UI items (log viewer, breadcrumbs, shared filter toolbar, destructive-action menus); polish/phone pass/Capacity tab are the next UI item. Business rules: no more setup complexity beyond what exists (viewing existing results, e.g. a Home Rules tab, is fine). See [[feedback-perfect-not-breadth]].

### feedback-ui-polish-direction

*2026-11-07 owner says the UI is boring/under-designed; polish is a major need; style mix Linear (highest weight) + Databricks + Datadog*

Owner: the current UI is "very boring", people would not want to keep working in it; UI/UX is lacking more than the backend. Wants a mix of Linear (highest weight: fast, keyboard-driven, crisp), Databricks (calm, dense layout, already approved) and Datadog (data-rich: sparklines, timelines, colour).

**Why:** adoption depends on the product being pleasant to use daily.
**How to apply:** make UI polish its own item, separate from the #363 redesign: foundation first (colour, type scale, layered surfaces, motion in shared components), then command palette, sparklines/timeline strips, log viewer, saved views, density switch. Review own screenshots (light/dark/390px) before showing. Keep the Databricks layout and status-colour rules. See [[feedback-ui-databricks-template]], [[feedback-review-own-screenshots]], [[project-2026-11-07-close]].

**2026-11-13 root cause (owner):** the "boring/soft" feel comes from font style, size and corner radius; edges should be sharper. Current tokens: radii 3/5/7/10/12/16 px (controls 7, cards 10, sheet 12), Inter Variable 14px base. Proposed: radii 2/3/4/6/8/10 (controls 4, cards 6, sheet 8, table cells 0, status pills round), 13px dense base, tighter heading tracking, tabular numerals, mono only for ids/targets/expressions, hairline borders not shadows. Do as its own item after the full-refresh PR, with before/after screenshots for approval.

**2026-11-13 (owner, after #392): no "pods".** Floating rounded content sheet, pill-shaped selected nav item and capsule header controls look like a "linux rice" desktop. Wants a conventional app frame: full-width header with a bottom divider, flush sidebar with a right divider, flat nav rows (2px accent bar + faint tint for selected, no pill), flush content with page-header divider, section dividers, a thin footer status bar, bordered 4px cards only for real groups. Palette: indigo is generic; retune violet-tinted neutrals to slate, accent (teal) only for primary action/selection/links/focus (it is used ~70 times now), cut 8 category hues to 3 muted by role. Plan: one "UI foundation" PR after #392 merges, before/after screenshots for owner approval (catalog, table page, pipeline page; light+dark; 1280+390).

**Control symmetry rule (owner, 2026-11-13):** header project dropdown, CUSTOM tag and search box differ in size/shape/radius (32/22/32px; "stickers"); controls must have symmetry in at least one direction, in several places. Plan: tokens for control height (28 dense / 32 default / 44 touch) and one control radius (4px); every control in a header/toolbar/filter row has the same height; project switcher + environment become one segmented control (prod stays red); status chips fixed 20px, never in a control row; lint forbids ad-hoc h-7/h-9/h-10/h-11 on controls; browser test measures control heights per toolbar across pages (±1px). Part of the same UI foundation PR as the flat frame and palette.

**2026-11-13 logo/banner (owner):** my converging-lines hexagon mark (#394, closed) "looks worse". Keep the original concept: a layered plane over a stem and stacked chevrons that reads like a tree. Change only colour and drawing style toward the reference (ftcdn snowflake-of-arrows line art: sharp mitered outline "double-line" strokes, no rounding). Owner generates the logo in ChatGPT and will supply the file. Banner = fastfetch-style: the logo as coloured ASCII/block art beside the info rows, plus a big "ETL-CRAFT" ASCII wordmark like Airflow's CLI; shown only at initialization. Build the banner from the supplied logo.

### snowflake-budget

*2026-11-12 Snowflake credit nearly gone (~$35); no Snowflake runs for PRs except affected tests of Snowflake dialect changes; full suite reserved for 0.9.0 release evidence*

2026-11-12: owner said Snowflake has about $35 of credit left.

**Why:** release evidence still needs one full Snowflake suite pass; routine PR acceptance would spend it.
**How to apply:** Codex prompts say Snowflake is "not run: credit reserved for release evidence" unless the change touches the Snowflake dialect, and then only the affected test files. Suggested XSMALL warehouse, AUTO_SUSPEND 60 and a resource monitor. An existing Snowflake protection-test ARRAY type mismatch (seen on the S7.AP branch) needs a separate fix. Overrides the parallel-cloud default in [[feedback-no-ci-timing-parallel-clouds]] and [[feedback-cloud-one-try]] for Snowflake.

### project-rebuild-plan

*2026-11-17 owner-agreed order of \"one complete implementation\" rebuilds found by the duct-tape audit*

Audit of patched-together aspects; owner: "I am fine with the rest". Order:
1. Engine DB baseline (in progress, branch refactor/engine-baseline): delete 97 migrations,
   conversion steps, legacy queries/registries; remaining: normalization.py,
   refresh_upgrade.py, upgrade_signin.py, part of schema_status.py; fix tests; baseline ledger
   entry + refusal of pre-0.9 Engine DBs. See [[project-baseline-squash]].
2. Warehouse legacy: upgrade-targets, rehash/hash versions, refuse_legacy side tables.
3. Readable schema.sql regeneration (both dialects), proven by catalog comparison; drops
   AUD_SOURCE_COLUMNS_BASELINE and AUD_CFG_SOURCE_COLUMNS_HISTORY.
4. Warehouse dialects: one dialect per database + per-table format strategy (native / Iceberg /
   Delta-UniForm), declared capabilities, feature modules, one registry, no spec.key branching
   outside dialects; golden-SQL tests prove byte-identical SQL (avoids cloud spend).
5. DONE #427/#428. Authorization: one evaluator, built-in CAN_* as stored action sets, declarative per-action rules.
6. DONE #429. Alerts: one ALERT task naming one channel of kind EMAIL/WEBHOOK/SLACK (Enforce_sla kept as per-env SLA_BREACH gate).
7. PR #430. Deploy: one application command `deploy` (+ `--plan`): bundle only when Artifacts.Store,
   config always, seeds only when declared ("no seeds declared" is not an error), pipelines
   refresh always; stops at first failure. Owner decided: REMOVE standalone bundle publish,
   config apply and seed apply; keep read-only config plan/export, validate, pipelines refresh.
8. DONE #424. Erasure at write (owner 2026-11-18, option 2): managed SQL/upload/seed writers get
   `(col IS NULL OR col NOT IN (:keys))` on each lineage-mapped column; a Python-script task
   deletes erased keys from its target inside the same attempt before succeeding;
   HANDLER=ERASURE deleted; `erase` keeps its one-time delete. Why: no daily re-run, and
   resent PII never creates new time-travel versions.
Warehouse PR decisions: rehash stays (design rule); upgrade-targets replaced by
`adopt-target` (rebuild + swap, original dropped by default, --keep-original keeps
<target>_pre_adopt), admin only, CLI/UI console only (no page).
Also to examine: pauses/controls cluster, 12 run-shaped reads, retention modules.

**Why:** [[feedback-one-complete-implementation]].

Step 7 choice: config applies only when config/ exists (migration-only projects). Next (owner request): UI "Refresh pipelines" button, RELAXED projects only, for callers who can refresh.

### project-baseline-squash

*2026-11-17 owner approved squashing all pre-0.9 Engine DB migrations into one 0.9.0 baseline; pre-0.9 upgrade support dropped*

Owner, 2026-11-17: nobody can install a version lower than 0.9.0 once it is public, so the Engine
DB upgrade path from 0.1.0–0.3.0 is dropped. Approved: one baseline schema per dialect at 0.9.0;
the 97 incremental migrations, conversion markers, `upgrade-targets` legacy SCD handling,
source/target contract conversion, legacy config-history rebuild and the 0.1.0–0.3.0 upgrade
tests are deleted; dev and demo Engine DBs are recreated. Migrations start empty after the
baseline and become immutable once 0.9.0 is tagged.

**Why:** the legacy upgrade code was the largest "pieces tied together" aspect
([[feedback-one-complete-implementation]]). Supersedes the older note that the 0.3.0 Engine DB
upgrade was still required ([[feedback-pre-1-0-breaks-ok]]).

**How to apply:** future Engine DB changes before 0.9.0 edit the baseline directly; after 0.9.0
they ship as new migrations from the baseline.

### feedback-one-complete-implementation

*2026-11-17 owner: build one complete, coherent implementation per aspect; break/delete old pieces freely before 0.9.0*

Owner, 2026-11-17 (during S7.B access redesign): "if something needs to be broken or deleted from
old code to make it coherent, do it. you dont need to tie to existing stuff if building complete
module is cleaner. this is not public yet ... no one can install a version that is lesser than
0.9.0 once it is public" and "same for anything in the application. if we have pieces tied
together. I would rather build one complete implementation for each aspect".

Owner, 2026-11-17: "how we reach the target can change before 0.9.0 ... what we do is a
discussion" — HOW (commands, modules, schemas, flags) is free to change; WHAT (capabilities,
behaviour users rely on) needs the owner first.

**Why:** pieced-together features (old grant columns + new roles, bulk CSV beside single grants)
are hard to reason about; nothing pre-0.9.0 has users, so compatibility shims cost without benefit.

**How to apply:** when extending an aspect, prefer rewriting it as one coherent module (rename
fields/flags/tables, delete superseded paths and formats) over adapters. Still ship migrations for
the Engine DB (immutable released files), still one PR per aspect, and say what was removed in
the PR. Proactively flag other aspects that are "pieces tied together" as candidates. Supersedes
the "breaks fine before 0.9.0" nuance only by making it the default. Related: [[feedback-pre-1-0-breaks-ok]].

### project-s7b-roles-design

*2026-11-17 owner-approved FINAL S7.B access model — one bindings table WHO/WHAT/WHERE, custom roles + single actions, environment scope, one PR*

Owner 2026-11-17 ("roles are needed. very much needed"; "make it one coherent setup ...
environments, projects, commands"). Approved final model, ONE PR:

- Every binding is WHO gets WHAT, WHERE, in one table `CFG_ACCESS_BINDINGS` that replaces
  `CFG_PIPELINE_GRANTS` (existing rows migrate as-is: PERMISSION -> ROLE_NAME).
  - WHO: `--account U | --group G | --audience viewer|operator` (GRANTEE_ROLE audience).
  - WHAT: `--role R` (built-in CAN_VIEW/CAN_UPLOAD/CAN_RUN/CAN_MANAGE, or custom) or
    `--action "run"` (one command).
  - WHERE: `--deployment` (every project) | `--environment PROD` (every project of that
    ENVIRONMENT_TYPE) | `--project P` [`--pipeline-code X` | `--tag T`].
- Roles: `CFG_ROLES` + `CFG_ROLE_ACTIONS`; built-ins uneditable; custom via
  `etl-craft role create|describe|add-action|remove-action|disable|list`.
- Allowed = any binding on deployment / the project's environment / the project / the pipeline
  or its tag includes the action. Built-in CAN_* keep today's level semantics (one level per
  principal per exact scope); custom roles/actions are additive.
- Deployment-only commands (accounts, pools, migrate) only in `--deployment` bindings.
- Account base roles (viewer..admin, CFG_ACCOUNTS.ROLE) stay; admin can do everything.
- `access explain --account A --action X --project P [--pipeline-code Q]`.
- Refusals: unknown / agent / host-only action; granting what you don't hold; editing built-ins;
  last admin. Groups already exist and are principals.

**Why:** unify S7.B custom roles with S7.Y CAN_* grants into one model the owner can reason
about. **How to apply:** record differences from item text in Handover notes; tests generated
from the action table; migration 0097 both dialects.

### project-homepage-video

*2026-11-16 etl-craft.dev homepage + product video planned together after S8 demo; Remotion official skills, Playwright footage*

2026-11-16 owner: the etl-craft.dev homepage (0.9.0 checklist, S7.J) also gets a product video.
Chosen tooling: Playwright records the real S8 Support Insights demo (light/dark), Remotion
(official `remotion-dev/skills`, installed from the official GitHub repo, not mirrors) composes
a 60–90 s captioned hero video plus a 15 s loop; no AI voiceover. brag/HyperFrames considered
and passed over. Both live in the `etl-craft.github.io` org repo, not the package repo.

**Why:** needs real demo screenshots/footage and a working install line, so built after S8;
published only at 0.9.0 ([[project-release-0-9-public]]).
**How to apply:** write homepage + video as one Codex prompt once S8 runs; check Remotion
licence terms (free ≤3-person companies) before use.

### docs-cleanup-before-0-9

*2026-11-12 owner agreed: before 0.9.0 delete planning docs (rewrite-plan, ui-wireframes, metadata-and-ui), unpublish and trim the roadmap, write docs/reference/design.md, regenerate screenshots*

Owner: before 0.9.0, clean up the planning files so only correct documentation remains.

Plan (owner asked to keep it in memory; not yet a roadmap item):
1. Delete `docs/development/rewrite-plan.md` and `docs/development/ui-wireframes/` (129 files, 1.9 MB).
2. Write `docs/reference/design.md` ("how etl-craft works and why") as current behaviour, from AGENTS.md design rules and handover decisions; fold what is still true from `metadata-and-ui.md` into it or the guides, then delete that file.
3. Remove the roadmap from `mkdocs.yml` nav and trim it to open items. It stays in the repo because AGENTS.md, the roadmap-item skill, the PR template, the PR policy check, `release/regressions.toml` and `scripts/check_regressions.py` read it. Moving to GitHub issues is after 0.9.0.
4. Commit only the screenshots the docs embed (`docs/assets/catalog`); regenerate them once in the release PR.

**Why:** the published docs site shows 10k lines of internal handover notes; stale wireframes and screenshots mislead users.
**How to apply:** do it as one `docs(plan)` PR after the last 0.9.0 roadmap item merges and before the release PR. Remind the owner when 0.9.0 items close. See [[project-release-0-9-public]].

### project-access-evaluator-decisions

*2026-11-18 owner decisions for the one-evaluator authorization PR (b): additive grants, pipeline grants open the project*

Authorization rebuild (plan step 5, option 1): PR a = decision matrix (#427, tests/fixtures/access_matrix.tsv); PR b = one evaluator with built-in CAN_* stored as CFG_ROLE_ACTIONS rows.

Owner decisions for PR b:
1. **Additive grants.** Project-wide grants (including viewer/operator audience defaults) always apply; a pipeline/tag grant only raises access on that pipeline. Today the first built-in grant on a pipeline/tag makes it private to its grantees — remove that.
2. **A pipeline/tag grant opens the project**, limited to the granted pipelines, so it always works. Today such a grant without project-wide access silently gives nothing.

**Why:** granting one person access must never hide a pipeline from others; a grant that does nothing violates fail-rather-than-guess.
**How to apply:** PR b re-records the matrix; the only allowed diffs are these two behaviours — list them in the PR. See [[project-rebuild-plan]].

### project-default-project-demo-only

*2026-11-18 owner: the seeded default project is only a showcase; admins deactivate it after install, so its open audience grants are fine*

The seeded `default` project (with viewer CAN_VIEW / operator CAN_RUN audience grants) exists only to show something after install; it is not meant for real use, and an admin deactivates it. Its broad grants are acceptable and need no change.

**Why:** owner confirmed after the additive-grants decision ([[project-access-evaluator-decisions]]), comparing with Databricks folder inheritance.
**How to apply:** don't propose removing the default project's audience grants; real projects come from `project add` and start with no grants.

### project-alerts-rebuild-decisions

*2026-11-18 owner decisions for rebuild step 6 (alerts): event-only ALERT tasks, email recipients on the channel, lean message settings*

Alerts rebuild (plan step 6), owner answers 2026-11-18:
1. **Event-only.** Every HANDLER=ALERT task is a subscription; the controller admits an isolated alert run per event. Run-end selectors SUCCESS and COMPLETED_WITH_ERRORS join FAILURE, SLA_BREACH, LOST, GATE_WAIT_OVER_n. The in-run end-of-pipeline email path is deleted; email gets retries and AUD_ALERT_DELIVERIES history.
2. **Recipients on the channel.** CFG_ALERT_CHANNELS gains KIND=EMAIL with an admin-owned RECIPIENTS list; EMAIL_TO is removed from tasks. The SMTP relay stays in craft-connector.yml Orchestration.Email.
3. **Lean content.** Optional ALERT_SUBJECT / ALERT_BODY ($$ tokens) for every kind; EMAIL_TEMPLATE, EMAIL_TEMPLATE_TEXT, EMAIL_PIPELINES for email channels. Per-outcome variants and EMAIL_ON_STATUS dropped (ALERT_ON; one task per selector for different wording).

**Why:** one admission → delivery → record path for every kind ([[feedback-one-complete-implementation]]).
**How to apply:** see [[project-rebuild-plan]] step 6; list these in the PR's Decisions.

### feedback-ui-reasons-hover-only

*Unavailable-action reasons in the UI appear only as hover/focus/tap annotations, never as text stamped on the page*

Grayed-out actions show their reason only as an annotation on hover, keyboard focus or tap
(`ui/src/components/action-reason.tsx`); never render it as a notice, caption or inline text.
Data explanations (pause reason, unmet dependency, lineage gaps) are not action reasons and may
stay visible.

**Why:** owner, 2026-11-23 during S7.AU: "you don't need to remind me even before me going for it".

**How to apply:** in UI reviews and Codex prompts, reject any persistent reason text for an
action's availability. Related: [[feedback-ui-status-colours]], [[feedback-shared-ui-components]].

### 2026-11-25-worklist

*Ordered open work after S8.C/S8.D findings - ROW_ID fix, S8.D close, UI/alert defects, re-parse rename, full-refresh-safe demo SQL*

Owner decisions 2026-11-25:
- Definition refresh is renamed **"re-parse"** (Airflow style): `pipelines re-parse`, UI "Re-parse pipeline/all". "Refresh" means data only (REFRESH_TYPE, --full-refresh). No alias pre-0.9.0. `lineage --refresh` is out of scope (ask).
- Demo must be **full-refresh safe**: SQL uses `$$pipeline_run_id_filter` (1=1 on full refresh), not `pipeline_run_id = $$pipeline_run_id`. 12 demo scripts were hard-coded. Full refresh rebuilds from PRS history, never depends on expiring sources. No ALLOW_FULL_REFRESH setting.
- Gamma stays on MinIO bucket notification -> signal row -> EVENT_SQL wait; EVENT_FILE does not list buckets. No demo file-wait change.

Order:
1. ROW_ID reuse fix (package, Codex in progress): Engine DB reservation before write, floor on removals, generator START above high-water, agent reservation report, post-write check.
2. S8.D close: repin, recreate PRE_ODS/flags, live acceptance, fact join bound to run, metrics validity incl. load rejects, demo PR + docs(plan).
3. UI/alert defects from SI_STEWARD_DS_AGENTS page: verify false FAILURE alert in a manual non-failed run (correctness, first); single-task manual run shown as "Latest run: Success"; alert task "Runs when: any upstream succeeds"; one delivery as 3 rows; run columns "SI_S..."; "Next run: Not started here" for upload/event-started pipelines (should say on upload / waits for object events).
FINDINGS 2026-11-26 (demo, package a0e08c64), root cause of "everything slow" + "logs only at end":
- NOTIFY storm: idle agent claim -> record_wait_reasons UPDATE AUD_TASK_ATTEMPTS (0 rows) -> FOR EACH STATEMENT trigger trg_notify_aud_task_attempts pg_notify -> wakes every claim long-poll (agent_claims.claim) -> repeat. 525 commits/s, 78 notifies/s with 0 QUEUED; UI pods ~1 core each, engine-1 0.8 core idle.
- `etl-craft agent health` imports the whole CLI: 2.1 s CPU per probe; 11 agents x liveness+readiness every 10 s = ~4-5 cores; near the 3 s timeout -> liveness restarts. renewal check alone ~0.1 s import.
- Live log transport WORKS (AUD_ATTEMPT_LOG_CHUNKS streamed within ~1 s, UI polls 3 s). Gap = 60-110 s silent task start (load above) + nothing logged before the handler. S7.AX.3 premise ("agents upload once at end") is wrong.
- Demo agent probes temporarily patched to a shell stat check via kubectl patch (reverted by next `kubectl apply -k infra/kubernetes`).
STATUS 2026-11-26: S7.AX.2b merged (#462, a0e08c64). Demo cluster updated to package main via update.sh (SI #34 fixed update.sh reading the pin); ci/PACKAGE_COMMIT still 468cd019 (bump with the next demo PR + build.sh). Next: recheck live refresh, then S7.AX.3 design note (live logs).
STATUS 2026-11-25 late: S7.AX.2a (pipeline page, filters, steward defects) = PR #461, auto-merge on. Next: S7.AX.2b run page (design https://claude.ai/artifact/Gf4FFMFkBkRXiExggb8svr), recheck live refresh after repinning the demo cluster to #461's merge. Old stash@{0} (fix/ui-interaction-usability) must stay untouched.
3b. Task-instance view redesign (owner 2026-11-25, screenshot of SI_SETUP run): Gantt fills the run tab and pushes task details below the fold; clicked task's card lacks its name; truncated names; nested scrolls; zero-count noise. Plan: grid cell opens a task panel (name, status, attempt picker; Overview / Log / SQL / Attempts tabs); timeline becomes its own run tab. Owner: I (Claude) build it myself right after S8.D closes (Codex out of quota). Scope widened same day (2nd screenshot): redesign the WHOLE pipeline-detail panel Airflow-dense — one scroll container with sticky task-name column (a scrollbar currently sits between names and cells, rows misalign), small cells (~12px) in ~24px rows, thin run-duration bars above columns, readable run headers, no per-row chevrons unless groups, timeline without checkmarks/queued boxes.
3e. Task log content (owner 2026-11-25: "very very basic"): add a context block (try, agent, connection, run date/params, watermark window, non-secret task params), rendered SQL per step (masked), rule flagged keys (capped), ROW_ID reserved range, Python source details, outcome block (status, rows, duration; on failure error + failing statement + class + remedy). Defect: SQL log line doubles the catalog ("warehouse.warehouse.pre_ods..."). Build with 3d after the panel redesign.
3f. S7.AX.2 filters (owner 2026-11-25): Excel-style checklist filters (shared ChecklistFilter, generalized from TagFilter): Tasks (rows), Task status = state in the SELECTED run, else newest visible run (owner chose option 1), Run status = server-side `run_status` on history (columns, paged). Default 10 runs, Airflow split 30/70 (graph 70/30), Grid/Gantt/Graph left switch, run tabs only Task instances + Details.
3g. UI does not refresh live: pages only update after a browser reload (owner 2026-11-25) - investigate in S7.AX.2 (polling/invalidation of grid, run, task queries).
3d. Live task logs (owner 2026-11-25): logs appear only after a task ends because remote agents upload the log once at the end (agent/loop.py). Needs periodic chunk upload from agents + streaming in the task panel; agent protocol + log storage change -> design note before building.
3c. UI slowness (measured 2026-11-25 on k3d): pipeline page 6.9 s / 34 API calls (one /history per task, 0.3-0.9 s each alone); pipelines list 12 s (one capabilities?definition=true per pipeline, 1-3 s each alone); runs page history?limit=50 ~2 s alone. Fix with the panel redesign: one grid endpoint per pipeline, one capabilities call per page, server-side query budgets per endpoint (like sql-statement-budgets), profile capabilities + history.
4. Re-parse rename (docs(plan) then package PR, demo follow-up).
5. Full-refresh-safe demo SQL slice (after 1-2).
6. Then S8.E, S8.F, S8.G, S8.H (+REJECT_LIMIT in demo), S8.A acceptance.
Snowflake: new trial account 2026-11-25 (token works; network policy on the service user only). Snowflake Postgres is not offered on this account's region/cloud (owner, 2026-11-25); owner skips that suite for now. Before 0.9.0 evidence: create one or decide to drop it.
Account region GCP_ME_CENTRAL2: no SNOWFLAKE_MANAGED volume. External volume ETL_CRAFT_ICEBERG on GCS bucket vcg-etl-craft-test (me-central1) WORKS (create/insert/merge/CTAS as ETL_CRAFT_TEST) once its SA got roles/storage.legacyBucketReader besides objectAdmin (091369 "retry" loop = missing storage.buckets.get). Cross-region worked. Cloud suite still hard-codes SNOWFLAKE_MANAGED: needs an optional ETL_CRAFT_TEST_SNOWFLAKE_EXTERNAL_VOLUME passed as EXTERNAL_VOLUME + BASE_LOCATION. Login user MCTECHIE has no policy; tests use service user ETL_CRAFT_TEST_SVC + role ETL_CRAFT_TEST. Owner 2026-11-25: customer (external) Iceberg volume is the better thing to test — real teams own their storage. .env has ETL_CRAFT_TEST_SNOWFLAKE_EXTERNAL_VOLUME=ETL_CRAFT_ICEBERG. 0.9.0 evidence can run on this account with the external volume; no AWS US account needed for Iceberg.
Backlog: SI issue #29, #440 leftovers (Accounts header 390px, ActionButton mapping), deploy ~156s perf, business-key per-run reject undercount (known limit), lineage --refresh naming.

Related: [[feedback_s8_defects_one_pr]], [[feedback_codex_builds_claude_architects]]

### ui-follow-airflow-for-pipeline-run-task-navigation

*2026-11-25 owner - pipeline, run, task and attempt views follow Airflow's grid + task-instance model; current pages \"not readable and usable\*

For the pipeline detail, run, task and attempt views, follow Airflow's information model and navigation (owner, 2026-11-25: "follow airflow bro. it makes it easy for everyone to understand information and navigate").

- One dense grid per pipeline: sticky task names, small status cells, thin run-duration bars on top; one scroll container.
- Selecting a cell opens the task instance beside the grid (not a separate page): header with task, run, status; tries as tabs; Logs first (live tail while running), then Details, the SQL/script that ran, attempts. Timeline is its own tab.
- Show only fields that apply to the state (no "Not recorded"/UNKNOWN/zero-count rows for a running attempt).

Reference to use (owner): https://airflow.apache.org/docs/apache-airflow/stable/ui.html - read it before designing these views.

**Why:** owner found the Databricks-style split panels, oversized cells, Gantt-first run tab and standalone attempt page unreadable; Airflow's layout is what users already know.
**How to apply:** Airflow is a behaviour/layout reference only (no copied assets, no comparison wording - see [[feedback_quietly_better]], [[feedback_no_reverse_engineering]]). Keeps the colour and hover-only-reason rules ([[feedback_ui_status_colours]], [[feedback_ui_reasons_hover_only]]). Supersedes [[feedback_ui_databricks_template]] for these views only.

### airflow-3-grid-task-instance-spec

*Concrete numbers and structure read from Airflow 3 React UI source for the S7.AX pipeline/run/task redesign*

Source: apache/airflow main, airflow-core/src/airflow/ui/src/layouts/Details/Grid/{constants.ts,Bar.tsx,GridTI.tsx,Grid.tsx,TaskNames.tsx,DurationAxis.tsx}, layouts/Details/{DetailsLayout.tsx,NavTabs.tsx}, pages/TaskInstance/{TaskInstance.tsx,Header.tsx,Logs/TaskLogHeader.tsx}. User docs: https://airflow.apache.org/docs/apache-airflow/stable/ui.html

- Grid: ROW_HEIGHT 20px; cell box 18px wide in a 20px row, no gap; state badge 14px tall, radius 4, state icon 10px inside, solid fill; selection outline 2px offset 1px.
- Run columns 18px wide; header 100px: duration bar height = duration/max(page)*100px, min 14px; axis lines at 100/50/4px with max and max/2 labels; click bar = select run.
- Task-name column: min 200px, sticky left (z1), header sticky top (z2); group indent depth*0.75+0.5rem; chevron toggles group.
- ONE scroll container; @tanstack/react-virtual, estimateSize 20, overscan 5; names and cells share the same virtual rows (this is what removes the names/cells seam).
- Layout: react-resizable-panels; grid panel default 20% (min 6), details 80% (min 20), persisted; collapse button on separator.
- Routes: /dags/:dag/runs/:run (run), .../tasks/:task (task instance), ?try_number for older tries (latest omits it).
- Task instance tabs order: Logs (default), Rendered templates, (XCom etc. N/A), Audit log, Code, Details. Header: name, state reason, operator, try (if >1), start, end, duration, version; actions Clear / Mark as.
- Logs header: level filter, search with next/prev, wrap/timestamp/level toggles, fullscreen, copy, download (logs_{dag}_{run}_{task}_{try}.txt).
- Behaviour reference only: no copied assets, no comparison wording ([[feedback_quietly_better]]). Our colours: [[feedback_ui_status_colours]].

Databricks run page (owner asked to mix it in, 2026-11-25; docs.databricks.com/gcp/en/jobs/monitor, the 2024 "enhanced workflows UI" blog, aws/en/ldp/monitoring-ui):
- Runs matrix: run-duration bar row + one cell per task; hover = start, duration, status. Open a run from its start time -> dedicated run page for only that run.
- Run page: header (status, start, duration, trigger, run-as, parameters, run id link back to the job); task views Graph | Timeline | List switched at the top; List = status, name, type, duration, dependencies, search by name, filter by status/type, sortable.
- Task click -> task run details (status, times, source code, compute + logs links, metrics) with an earlier-attempt dropdown. Failed nodes highlighted on the graph; "refresh failed only" style recovery.
- Plan (proposed to owner, awaiting OK): grid page keeps the Airflow side panel for quick look; "Open run" / column link opens a full-width run page (header + Graph|List|Gantt + same task panel), as a second S7.AX.2 PR.
- Owner decisions 2026-11-25 on the design page (https://claude.ai/artifact/Gf4FFMFkBkRXiExggb8svr): run page is a second PR S7.AX.2b; run task list shows rows as THREE columns (in, written, rejected); Recover menu names kept: "Recover failed tasks", "Recover from a task", "Rerun the whole run".

### one-open-plan-pr-at-a-time

*2026-11-25 owner flagged parallel docs(plan) PRs all editing road-to-1.0.0.md; batch plan changes into one PR*

Keep at most one open `docs(plan)` PR editing `docs/development/road-to-1.0.0.md`. When more plan changes come up while one is open, add them to that PR's branch instead of opening another.

**Why:** owner, 2026-11-25: "all your PRs change the same file, you will create merge conflicts". That time #457/#458/#459 happened to merge cleanly (checked with `git merge-tree`), but the status-table rows sat a few lines apart and auto-merge would stall on a conflict.
**How to apply:** before opening a plan PR, `gh pr list --search "docs(plan)" --state open`; if one exists, commit to its branch and update its description. If two are unavoidable, verify with `git merge-tree --write-tree origin/<a> origin/<b>`. Related: [[feedback_one_pr]].

