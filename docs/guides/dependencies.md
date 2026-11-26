# Run conditions

Set `RUN_CONDITION` in `tasks.csv` to say when a task starts. A blank cell makes the
task ready when the pipeline run starts. Deploy, project migrations and
`etl-craft pipelines re-parse` derive the dependency edges from the conditions.

## Expressions and facts

Use a task code followed by a fact, such as `load.SUCCESS`, `pipeline.load.FAILED`, or
`project.pipeline.load.FINISHED`. Keywords and facts are case-insensitive. You can
combine expressions with `NOT`, `AND`, and `OR`, in that order of precedence.
Parentheses group expressions, and `AT_LEAST(2, a.SUCCESS, b.SUCCESS, c.SUCCESS)`
requires at least two of the three expressions to be true. The threshold must be
between one and the number of expressions.

| Facts | Values |
|---|---|
| `SUCCESS`, `FAILED`, `SKIPPED`, `FINISHED`, `HAS_DATA` | Boolean. `HAS_DATA` requires a successful task that wrote at least one row. |
| `STATUS` | `SUCCESS`, `FAILED`, `SKIPPED` or `CANCELLED` |
| `SOURCE_ROWS`, `TARGET_ROWS`, `ROWS_WRITTEN`, `INSERTED`, `UPDATED`, `DELETED`, `REJECTED`, `DUPLICATES`, `ATTEMPTS`, `DURATION_SECONDS` | Integer |
| `ERROR_CLASS` | `TRANSIENT`, `PERMANENT`, `UNKNOWN` or `NONE` |

Compare numeric facts with `=`, `<>`, `<`, `<=`, `>`, or `>=`. Use `=` or `<>`
for status and error class, for example `load.STATUS = FAILED`.

The package demo's `DEMO.setup_fact` waits for
`interactions.SUCCESS AND interactions.ROWS_WRITTEN > 0 AND retire_agents.SUCCESS`.
See the [demo metadata](https://github.com/etl-craft/etl-craft/blob/main/examples/demo/metadata/demo.sql).

## When a task starts

A true expression makes the task ready. A false expression skips it. An unknown
expression waits. For example, `a.SUCCESS OR b.SUCCESS` is true as soon as either
task succeeds. A count that a handler does not report is unknown. If no upstream
can still change the answer, an unknown expression also skips the task. The
engine records the reason and the values it read in `AUD_GATE_DECISIONS`.

Tasks in the same pipeline read each other's state under the same run. A failed
upstream may still be retried, so its dependents wait until that failure is final.
Tasks already successful or skipped under the run stay settled.

## Dependencies on other pipelines

A reference to another pipeline reads the latest finished output. The gate can
wait for an upstream run still in progress and checks that the output was not
already consumed. A successful task consumes the output recorded at admission.
Set `CONSUME_REPAIRS=N` on the consuming pipeline to accept only a new run
identity for task conditions. Pipeline-level dependencies still use `pipeline_dependencies.csv` and its
`DEPENDENCY_TYPE`: `SUCCESS`, `FAILURE`, `ALWAYS`, or `HAS_DATA`. They are
checked before admitting a pipeline run. An unmet pipeline gate produces a
skipped pipeline run. Each pipeline dependency has its own `CONSUME_REPAIRS`.

Backfills assume cross-pipeline tasks delivered. They read `SUCCESS`, `FINISHED`
and `HAS_DATA` as true, `FAILED` and `SKIPPED` as false, and `STATUS` as
`SUCCESS`. Other cross-pipeline facts are unknown.

## Refusals

Correct a misspelling such as `load.SUCESS` to `load.SUCCESS`. Use a numeric fact
in a comparison such as `load.REJECTED = 0`. Remove self-references or one link
in a cycle, and use only active tasks in projects you can view.

## How a pipeline run ends

Each task, including an alert, accepts these options in `task_parameters.csv`.

| Option | Default | Effect when set to `Y` |
|---|---|---|
| `FAIL_PIPELINE_IF_FAILED` | `Y` | Its final failure fails the pipeline. |
| `FAIL_PIPELINE_IF_NOT_RUN` | `N` | A skip caused by its condition fails the pipeline. |

Other branches continue. An operator's skip does not trigger the second option,
and a cancelled run stays cancelled. Engine trouble that leaves a task without a
final outcome fails the pipeline. If no failure applies and every data task was
skipped, the pipeline is skipped. In an alert-only pipeline this test includes
every alert. Other runs succeed.

For example, set `FAIL_PIPELINE_IF_FAILED=N` on `load_optional` and give a
notification task the condition `load_optional.FAILED`. An exhausted retry
leaves the load recorded as failed and starts the notification. The pipeline can
succeed, with the tolerated failure named in its outcome.
