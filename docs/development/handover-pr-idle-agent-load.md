## Summary

Fixes found on the Support Insights cluster (11 agents, 2 UI copies, PostgreSQL Engine DB, package `a0e08c64`), where every page was slow and running tasks showed no log until they ended.

- **Idle agents kept the API and Engine DB busy.** A claim that found no work ran the wait-reason `UPDATE AUD_TASK_ATTEMPTS ... WHERE STATUS='QUEUED'`. With nothing queued it changed no row, but `trg_notify_aud_task_attempts` was `FOR EACH STATEMENT`, so it still sent `pg_notify`. Every waiting claim woke, ran the same update and signalled again. Measured idle: 525 commits/s, 78 notifications/s, about 1 core per UI copy and 0.8 core on the Engine DB. The three notify triggers are now row-level (PostgreSQL folds identical notifications in a transaction), and `placement_wait_reasons` writes only attempts whose reason changes.
- **`etl-craft agent health` cost about 2 s of CPU** because `etl_craft.cli` imported the whole command tree. Kubernetes runs it twice every 10 s per agent (about 4-5 cores for 11 agents) against a 3 s timeout, which also caused liveness restarts. `etl_craft.cli.main` now answers `agent health [--project-dir D | --config F]` before importing the commands: about 0.13 s. Every other form, including `--project-dir` with `--config`, goes to the full command line as before. The CLI body moved to `etl_craft.cli.app`.
- **A running task's log was empty until its handler logged.** The agent now writes the first line when it takes the task (attempt, try, task, agent, host, pool, slot), and the task process logs loading the bundle (with seconds) and starting the handler.
- **The agent's task process logged under `__main__`** (it runs as `python -m etl_craft.agent.child`), so everything it logged was dropped, including `agent task failed` and the traceback of a failed task. Its logger is now named `etl_craft.agent.child`.
- **Toolbar alignment in the UI.** `Field compact` stacked its label above the control, so each labelled filter sat lower than the buttons and inputs beside it (task log, Runs, run page Events, catalog, scheduled, admin, dashboard). Compact labels now sit beside their control on one line, and the toolbars that bottom-aligned items to compensate now centre them.

## Roadmap item

S8 defects found on the Support Insights demo (S8.D follow-up); also covers the symptom S7.AX.3 was planned for.

- [x] An idle deployment sends no execution notification and writes no unchanged wait reason.
- [x] The agent health probe answers without loading the command tree.
- [x] A running agent task's log starts when the agent takes the task, and the task process's own lines reach it.
- [x] Toolbar filters align with the controls beside them.

## Decisions

- **Row-level notify triggers** rather than statement triggers with transition tables: one trigger per table stays, and a statement that changes nothing sends nothing.
- **The SQLite wait-reason query uses `IS NOT`** (null-safe; the supported minimum, SQLite 3.35, lacks `IS DISTINCT FROM`). The PostgreSQL override uses `IS DISTINCT FROM`.
- **The health fast path parses only its two options** and hands anything else to the full parser, so there is still one implementation of the command line. The check itself is one function (`cli.agent_health.agent_health`), used by both paths.
- **The process-boundary handler for unexpected errors moved into `etl_craft.cli.main`,** so `app.main` keeps only `EtlCraftError` handling. Output and exit code are unchanged (`error: unexpected <Type>: <message>`, exit 16).
- **The agent's start line is formatted by `core.log.text_line`,** which shares its formatter with `log.configure`.

## Concerns and deviations

- **S7.AX.3's premise doesn't hold.** Agents already upload log chunks while a task runs (`AUD_ATTEMPT_LOG_CHUNKS`, sent within about 1 s), `attempt_log` serves them for a live attempt, and the UI refetches every 3 s. The "no log until the end" symptom came from the load above plus nothing being logged before the handler. This PR fixes both. Re-scoping S7.AX.3 belongs in the next `docs(plan)` PR.
- **The demo's agent probes were patched by hand** to a shell timestamp check while measuring. The next `kubectl apply -k infra/kubernetes` restores the package's probe, which is now cheap.
- **Engine DB:** pre-0.9.0 `schema.sql` edit (trigger level only). Existing development Engine DBs keep statement triggers until they're recreated, or until the three triggers are recreated by hand.

## New public surface and dependencies

None. `etl_craft.cli.build_parser` moved to `etl_craft.cli.app.build_parser` (internal; the docs generator and tests updated).

## Validation

- `make static`: passed. `make docs` (strict): passed.
- Unit + touched integration suites (`tests/unit`, engine notifications, project bundles, query plans, actor audit, agent process and API, recovery controls, controller server; `-n 4`): 4,771 passed, then 4,706 passed after the CLI changes. The docs-generator import was fixed afterwards; `test_live_documentation.py`: 5 passed.
- New tests that fail on main:
  - `test_wait_reasons_signal_waiting_claims_only_when_a_reason_changes` (PostgreSQL; a sentinel notification bounds the read, so there are no timing waits);
  - `test_the_health_probe_answers_without_loading_the_command_tree` (both cases);
  - `test_agent_runs_its_pinned_bundle_without_engine_or_store_credentials` (start, bundle and handler lines, in order);
  - `test_agent_terminal_exit_records_real_evidence[FAILED]` (the traceback reaches the task log).
- Measured on the demo: the probe took 2,116 ms in an agent pod; locally the new path takes 133 ms. Host load fell from 13.7 to 7 with cheap probes alone.
- BROWSER_PLACEHOLDER
- Not run: cloud warehouses (no warehouse SQL changed).

## Handover

- After merge: recreate the three notify triggers on the demo Engine DB, update the cluster with `update.sh`, re-apply the manifests (package probe), then recheck idle commit rate, task start times, live logs and live refresh.
- Next `docs(plan)` PR: re-scope S7.AX.3 (see Concerns).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01UduYYBkXxh59s6HLSSyq5g
