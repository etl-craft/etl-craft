# Running a pipeline

## Running every task

```bash
etl-craft run --reason "requested data load" --pipeline-code SALES_DAILY
```

This runs every active task under one pipeline run. Each completion releases any
newly ready tasks immediately; a slow independent task does not hold back another branch.
At most `CFG_PIPELINES.MAX_PARALLEL_TASKS` tasks run at once (8 unless set), each in its own
process with the same logs, time limits and outcomes as [`run --task-code`](running-tasks.md).
`Orchestration.Local_python_slots` caps how many of them run Python tasks, and
`Orchestration.Local_warehouse_slots` how many run SQL, business-rule and alert tasks; unset,
either kind may use every slot. A task waits for a free slot of its own kind, while tasks of the
other kind keep starting.
Cross-pipeline gate waits persist their deadline and next look without holding an agent slot.

```
INFO etl_craft.execution.scheduler [pipeline=SALES_DAILY pipeline_run_id=97]: SALES_DAILY: dispatch extract_orders
INFO etl_craft.execution.scheduler [pipeline=SALES_DAILY pipeline_run_id=97]: SALES_DAILY: dispatch extract_customers
INFO etl_craft.execution.scheduler [pipeline=SALES_DAILY pipeline_run_id=97]: SALES_DAILY: dispatch load_orders
```

The run ends `SUCCESS` when every data task is `SUCCESS` or `SKIPPED`, `SKIPPED` when every data task is
`SKIPPED`, and `FAILED` otherwise; the command exits `1` for a failed run and `0` otherwise. A failed run names each task that did not succeed:

```
SALES_DAILY: pipeline_run_id=97 FAILED — 2 task(s) did not succeed: load_orders (FAILED), publish (never started); 1 of them could not start because their dependencies were not met
```

A task whose dependencies can never be met under the run is recorded `SKIPPED`, and stays
`SKIPPED`: see [Dependencies and run conditions](dependencies.md).

## One-run task input overrides

Use a repeated `--param TASK.PARAM=VALUE` and a stable `--request-key` to change existing
inputs for one new run, without editing the pipeline's configuration:

```bash
etl-craft run --pipeline-code SALES_DAILY --init-only --reason "reprocess one day" \
  --request-key sales-2026-11-10 \
  --param 'extract_orders.INPUT_PARAMS={"day":"2026-11-10"}'
```

The task must already have that active parameter. The initial supported data inputs are Python
`INPUT_PARAMS` (a JSON object), and SQL `ALLOW_EMPTY` (`true`/`false`), `REJECT_LIMIT` (the handler's row
count/percentage budget) and `WATERMARK_START` (the configured watermark type). Code, targets,
credentials and execution controls cannot be overridden. `WATERMARK_START` remains a seed:
a retained checkpoint still takes precedence; an override never resets it. Malformed assignments, duplicate
keys, unknown tasks/names and invalid values refuse before a run is accepted. Split at the
first equals sign; later equals signs are part of the value. Quote a value for your shell
when it contains spaces or JSON punctuation.

Overrides apply to a new whole-pipeline or `--init-only` run, or a new `--standalone` task
selection. Backfill, skip, force, rerun and mutation of an existing run are refused. The shared
RUN operation enforces the usual operator role, project/pipeline grants, governance reason
and production confirmation. The HTTP RUN request accepts the same strings as `params` and
`request_key`; the Run now dialog sends that same request.

The run and its actor-attributed `AUD_RUN_PARAMETER_OVERRIDES` row commit together.
Raw assignment strings are omitted from the general action-request audit; accepted values
live in the guarded override record. Credential assignments are refused without echoing
the supplied value. The base
metadata snapshot remains unchanged; one effective-definition reader overlays the recorded
values on it. Retries, recovery and agent dispatch read those values even after configuration
changes. The run document's `parameter_overrides` and its Recorded task inputs panel explain
which values differ from the base. Unlisted values retain their pinned defaults.

Reusing a submission key in the same project with the same canonical inputs returns the
recorded run without dispatching it again. Reordering assignments does not change identity;
changing task, pipeline, logical date, selection or values refuses. Use a new key for new
work. The submission record is retained with the run; after run retention removes it,
there is no replay record. Use a unique key for each logical submission. An accepted override run remains recorded if a later connection preflight fails;
reusing its key returns its current state. Resume that exact run without new overrides after
repairing the connection. An explicit restart copies overrides to its newly pinned base, refusing incompatible
task/name/type changes before creation. Replay of an accepted restart retains that exact
replacement and its recorded values.

## Before the run starts

The engine first tests the connections the run uses. A warehouse failure stops with exit status
`11` (`CONNECTION_TEST`), naming the failure; nothing is recorded and no task starts. An email
failure is logged and data tasks may still run; the alert task records any delivery failure.

| Tested | When |
|---|---|
| the warehouse | a task's `HANDLER` is `SQL` or `BUSINESS_RULES`, or cloning is on |
| the email relay | a task's `HANDLER` is `EMAIL_ALERT`, or `Enforce_sla` is on and the pipeline has an `SLA_IN_HOURS` |

A DuckDB file warehouse is not tested: there is no server to be down, and a running task may hold
its one writer's lock.

Email alert failures do not change the outcome of a pipeline containing data tasks; see
[Email alerts](email-alerts.md#when-sending-fails). A pipeline containing only alerts uses their
outcomes.

A new run is recorded `QUEUED` while its dependencies on other pipelines are checked.
`AUD_GATE_WAITS` retains its deadline and look count across restarts; admission changes it
to `IN-PROGRESS` only when there is no active sibling. When one is not
satisfied, the run is recorded `SKIPPED` with the reason, no task runs, and the command exits
`0`:

```
SALES_DAILY: pipeline_run_id=98 SKIPPED — upstream pipeline ORDERS_INGEST (SUCCESS) last finished run 41 ended FAILED, which does not satisfy a SUCCESS dependency
```

See [Dependencies on other pipelines](dependencies.md#dependencies-on-other-pipelines).

## Resuming a run

A run that is still `QUEUED` or `IN-PROGRESS`, for example because its process was stopped, is resumed by
running the pipeline again: its `SUCCESS` and `SKIPPED` tasks are not run again, and its failed
tasks get another attempt. An admitted run does not check the pipeline's dependencies again; a queued run resumes its
recorded gate budget.

Pressing Ctrl-C, or sending the process `SIGTERM` or `SIGHUP`, stops every running task's
process. The command stops at its next safe point, between Engine DB transactions, so an
interrupted transaction never leaves the Engine DB locked. A second signal while the first still
waits for a safe point stops it at once; one that arrives while the command is stopping its tasks
takes effect when they have stopped.
Those tasks are recorded `FAILED`, and the run stays `IN-PROGRESS` so the next run
resumes it. The same holds for `run --task-code`, `--rerun` and `--backfill`. `SIGKILL` cannot be
caught: the next run reconciles expired leases, records orphaned attempts `LOST`, stops
verified local children and retries failed tasks. `etl-craft reconcile` also requests recovery.
See [run controls](run-control.md#mark-a-task) for grace periods and uncertain side effects.

`--force` runs every task after its same-pipeline upstreams finish, regardless of their outcomes
or its previous status, and skips the
pipeline's dependency check. It requires local execution.

To step in on a run (mark a task or the run, record a stand-in upstream run, cancel it, run a
task again or without its dependencies, or relax dependency gates), see
[Stepping in](run-control.md).

## Initialize for the controller

`etl-craft run --pipeline-code SALES_DAILY --init-only` tests connections, checks pipeline
dependencies and creates or resumes the selected run. A running controller picks it up.
Another scheduler can [submit a run over HTTP](../deploying/http-api.md#starting-runs-from-another-scheduler).

## SLA

Every run of a pipeline with `SLA_IN_HOURS` is marked in `AUD_PIPELINES_RUN_LOG.SLA_STATUS`:
`MET`, or `BREACHED` when the run took longer. While a local run is going, it is marked
`BREACHED` as soon as the SLA passes, with a warning in the log; otherwise it is marked when the
run ends. A run's `STATUS` does not change either way: a late run still did its work.

With `Orchestration.Enforce_sla: true`, a breach also sends an SLA email through the `Email`
settings, once per run.

## Unfinished commands

A whole-run command that leaves its run unfinished exits `22` (`INCOMPLETE`), including a
pause during execution or work owned by another process. A stopped backfill also exits `22`
unless its stopping outcome failed or was cancelled (exit `1`). A paused pipeline that starts
nothing retains exit `0`, as does `--init-only`, which deliberately initializes a run for later
steps. Dependency waits that record nothing in `run --task-code` exit `23` (`WAITING`).
Use [`status` and `explain`](inspecting.md) to inspect the selected run before resuming it.

Run requests require `--reason REASON` in a STRICT project, including non-production projects.
RELAXED projects allow it to be omitted. Production projects always use STRICT governance.
The CLI, API and browser apply the same project policy.
