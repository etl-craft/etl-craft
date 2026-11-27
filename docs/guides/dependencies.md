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
between one and the number of expressions, with at least two expressions. The
last part of a reference is always the fact. Task conditions use
`task.FACT`, `pipeline.task.FACT` or `project.pipeline.task.FACT`. Start
conditions use `pipeline.FACT` or `project.pipeline.FACT`. Conditions support
boolean combinations and typed comparisons. Arithmetic, templating and other
functions are unavailable.

| Facts | Values |
|---|---|
| `SUCCESS`, `FAILED`, `SKIPPED`, `FINISHED`, `HAS_DATA` | Boolean. `HAS_DATA` requires a successful task that wrote at least one row. |
| `STATUS` | `SUCCESS`, `FAILED`, `SKIPPED` or `CANCELLED` |
| `SOURCE_ROWS`, `TARGET_ROWS`, `ROWS_WRITTEN`, `INSERTED`, `UPDATED`, `DELETED`, `REJECTED`, `DUPLICATES`, `ATTEMPTS`, `DURATION_SECONDS` | Integer |
| `ERROR_CLASS` | `TRANSIENT`, `PERMANENT`, `UNKNOWN` or `NONE` |

Compare numeric facts with `=`, `<>`, `<`, `<=`, `>`, or `>=`. Use `=` or `<>`
for status and error class, for example `load.STATUS = FAILED`.
Use boolean facts directly, for example `load.FINISHED AND NOT load.FAILED`.
A skipped task contributes zero to counts. A measurement the handler did not
report remains unknown.

The package demo's `DEMO.setup_fact` waits for
`interactions.SUCCESS AND interactions.ROWS_WRITTEN > 0 AND retire_agents.SUCCESS`.
See the [demo metadata](https://github.com/etl-craft/etl-craft/blob/main/examples/demo/metadata/demo.sql).

## When a task starts

A true expression makes the task ready. A false expression skips it. An unknown
expression waits. `NOT` leaves an unknown value unknown. False decides an
`AND` even if the other operand is unknown, and true decides an `OR` in the
same situation. `AT_LEAST` is false once even counting all unknown terms cannot
reach the threshold. For example, `a.SUCCESS OR b.SUCCESS` is true as soon as either
task succeeds. A count that a handler does not report is unknown. If no upstream
can still change the answer, an unknown expression also skips the task. The
engine records the reason and the values it read in `AUD_GATE_DECISIONS`.

Tasks in the same pipeline read each other's state under the same run. A failed
upstream may still be retried, so its dependents wait until that failure is final.
Tasks already successful or skipped under the run stay settled.

## Dependencies on other pipelines

A reference to another pipeline reads the latest finished output. The gate can
wait up to `Orchestration.Gate_wait_minutes` for a fresh output and checks that
the output was not already consumed. A successful task consumes the output
recorded at admission. Backfill runs are not eligible upstream outputs.
Set `CONSUME_REPAIRS=N` on the consuming pipeline to accept only a new run
identity for both task conditions and the start condition.

Backfills assume cross-pipeline tasks delivered. They read `SUCCESS`, `FINISHED`
and `HAS_DATA` as true, `FAILED` and `SKIPPED` as false, and `STATUS` as
`SUCCESS`. Other cross-pipeline facts are unknown.

## Start conditions

Set `START_CONDITION` in `pipelines.csv` to gate admission on another pipeline's output.
For example, `SALES_DAILY.SUCCESS AND finance.LEDGER.REJECTED = 0` reads a pipeline
in the same project and a pipeline in the finance project. Leave the cell empty
to start without an upstream gate. Deploy and re-parse derive the edges.

Pipeline conditions use the same operators and facts as task conditions, except
`ATTEMPTS` and `ERROR_CLASS` are unavailable. Status and duration come from the
bound run. Counts are summed over its task runs. Skipped tasks contribute zero,
and a count with no reported values stays unknown. `HAS_DATA` reads whether
a successful run wrote rows.

Each name binds to the latest finished run outside backfills, provided its output
is fresh for this consumer. The pipeline's `CONSUME_REPAIRS` defaults to `Y`,
so a newer revision of an already consumed run is fresh. Set it to `N` to
require a new run ID. A successful consumer records the bound outputs once.
A successful upstream with tolerated task failures still publishes fresh output.

True starts the run. False skips it. An unknown condition waits up to
`Orchestration.Gate_wait_minutes`, then skips if it is still unknown. The gate
records the condition and the values read. `Dependency_gates: WARN` allows an
unmet condition to run and records the bypass. `OFF` bypasses every edge without
evaluating the condition.

Backfills use the delivered facts above for every referenced pipeline. If those
facts leave the expression unknown, the condition is unmet. Backfills consume
no upstream output.

Use `pipeline.FACT` or `project.pipeline.FACT` and reference active pipelines
in projects you can view. Deploy and re-parse refuse unavailable facts,
self-references and cycles through start conditions, including across projects.

## Refusals

Deploy, config plan, validate and re-parse can refuse an invalid condition. Use
the named task or pipeline and expression position to find the error. Correct a
misspelling such as `load.SUCESS` to `load.SUCCESS`. Use a numeric fact in a
comparison such as `load.REJECTED = 0` and choose a fact available for the
condition's scope. Remove self-references or one link in a cycle, and use only
active upstreams in projects you can view.

## Changing a task other projects name

Deploy and config plan refuse to retire a task or pipeline still named by an active
condition in another project. Retiring the old key and adding a new key follows the same
rule. Validate reports existing broken inbound conditions on the upstream row.

Change the downstream condition or deactivate the task or pipeline that owns it, then
deploy that project first. Once its condition no longer names the old upstream, deploy
the upstream change. If you cannot view the dependent, the refusal says
`a task in another project depends on <upstream>; ask an administrator`.

## How a pipeline run ends

The pipeline run is a container for its task runs. Each task, including an
alert, accepts these options in `task_parameters.csv`.

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
