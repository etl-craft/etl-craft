# Concepts

These are the identities, capacity limits and project boundaries used by the CLI.

## Runs

A run is one execution of a pipeline, recorded in `AUD_PIPELINES_RUN_LOG`. Tasks belong to
that run; their caller supplies its identity. Commands select `--run-id`, `--run-key`, or the
single non-terminal whole-pipeline run (`QUEUED` or `IN-PROGRESS`). Nothing selects a run by
recency. Ended runs and resuming manual task selections require an explicit identity.
See [Running a pipeline](guides/running-pipelines.md).

```bash
etl-craft run --pipeline-code SALES --run-id 42
```

## Attempts

An attempt is one try at executing a task under a run, recorded in `AUD_TASK_ATTEMPTS`.
A retry creates a new attempt and resumes the run: tasks already `SUCCESS` or `SKIPPED`
are not re-run. To deliberately run completed work again, use the explicit rerun controls.
See [Running a task and reading its logs](guides/running-tasks.md).

## Run keys

A run key is a stable text identity unique within a pipeline; the numeric run id identifies
the same run. Reusing a key selects that run rather than creating another execution with the
same key. Choose either `--run-key` or `--run-id`, never both.
See [Running a pipeline](guides/running-pipelines.md).

## Revisions

An output revision identifies a run's published output for cross-pipeline consumption.
Repairing a run publishes one new revision only when it ends `SUCCESS`, not after each repaired
task. A dependency accepts a newer revision of the same consumed run as fresh only when
`CONSUME_REPAIRS=Y`; `N` requires a new run instead. Admission records the consumption decision
so completion does not judge freshness again.
See [Dependencies and run conditions](guides/dependencies.md).

## Leases

A lease records who currently owns a run or attempt. Whole-pipeline and task supervisors
renew 60-second leases every 15 seconds. An expired attempt must be reconciled as `LOST`
before a retry; a new supervisor cannot simply adopt it.
See [Controller recovery](deploying/controller.md).

## Pools

A pool is the execution capacity to which tasks are dispatched. Slot kinds are `python` for
`PYTHON` and `FILE_VALIDATION`, and `warehouse` for the other handlers. An attempt reserves
its slot kind for its whole execution; an unavailable slot means waiting, not extra capacity.
Dependency gate waits consume no agent slots.
See [Agents and the queue](deploying/agents.md).

## Projects

A project contains pipeline definitions and its connection configuration. It has one
warehouse; several projects may share an Engine DB. Selecting `--project` does not grant
access to that project: its bindings still apply.
See [Operating a server from your own installation](guides/remote-cli.md).

## Environments

A project's environment type is `DEV`, `SIT`, `UAT`, `PROD`, `SANDBOX` or `CUSTOM`; its
optional environment name identifies it more specifically. Governance is `STRICT` or
`RELAXED`. Only deployment admins change these fields, and `PROD` cannot be `RELAXED`.
`RELAXED` allows empty intervention reasons; it does not relax authorization or auditing.
See [Environments and governance](guides/access.md#environments-and-governance).
