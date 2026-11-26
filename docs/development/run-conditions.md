# Run conditions (S7.BA design note)

Status: approved by the owner; S7.BA.2 builds it. Behaviour reference: PowerCenter 10.5.1
link conditions, predefined task variables and AND/OR input links (Workflow Basics guide,
chapters 2 and 5; Advanced Workflow guide, chapter 14).

## What changes for a team

Today a start rule is spread over three files: `task_dependencies.csv` (one row per upstream,
with `DEPENDENCY_TYPE`), `pipeline_dependencies.csv`, and `RUN_CONDITION` /
`RUN_CONDITION_COUNT` in `tasks.csv`. After S7.BA each rule is one cell on the row it governs:

```csv
PIPELINE_CODE,TASK_CODE,...,RUN_CONDITION
SI_CLIENT_ALPHA,alpha_prs_to_cdc,...,alpha_lnd_to_prs.HAS_DATA
SI_CLIENT_ALPHA,alpha_cdc_to_preods,...,alpha_prs_to_cdc.SUCCESS AND alpha_preods_delete.SUCCESS
SI_CLIENT_ALPHA,alpha_failure_alert,...,AT_LEAST(1, alpha_lnd_to_prs.FAILED, alpha_prs_to_cdc.FAILED)
SI_DM,dm_fact,...,SI_CLIENT_ALPHA.alpha_preods_to_ods.SUCCESS AND dm_dims.SUCCESS
```

```csv
PIPELINE_CODE,...,START_CONDITION,CONSUME_REPAIRS
SI_VIEWS,...,SI_DM.SUCCESS AND SI_DM.REJECTED = 0,Y
```

`task_dependencies.csv`, `pipeline_dependencies.csv` and `RUN_CONDITION_COUNT` go away.

## Grammar

A closed grammar: no functions other than `AT_LEAST`, no arithmetic, no templating.
Keywords and facts are case-insensitive; names match codes as `deploy` matches them today.

```text
condition  := or
or         := and ("OR" and)*
and        := not ("AND" not)*
not        := "NOT" not | primary
primary    := "(" or ")" | at_least | comparison | flag
at_least   := "AT_LEAST" "(" integer "," or ("," or)+ ")"
comparison := ref op value
flag       := ref                       -- a boolean fact: ref ends in a boolean fact
op         := "=" | "<>" | "<" | "<=" | ">" | ">="
value      := integer | keyword
ref        := name "." FACT
name       := code | code "." code | code "." code "." code
```

The last segment of a reference is always the fact, so `a.b.SUCCESS` is pipeline `a`, task `b`.

| Where | `name` with 1 part | 2 parts | 3 parts |
|---|---|---|---|
| `CFG_TASKS.RUN_CONDITION` | a task in the same pipeline | `pipeline.task` | `project.pipeline.task` |
| `CFG_PIPELINES.START_CONDITION` | a pipeline in the same project | `project.pipeline` | refused |

An empty condition means no upstream: the task starts when its run starts, and the pipeline starts
on its schedule or request as today.

## Facts

Facts are read from the audit tables of the run the name binds to (see Binding).

| Fact | Type | Task: read from | Pipeline: read from |
|---|---|---|---|
| `SUCCESS`, `FAILED`, `SKIPPED` | boolean | `AUD_TASK_RUN_LOG.STATUS` | run status |
| `FINISHED` | boolean | status is terminal | run status is terminal |
| `HAS_DATA` | boolean | `SUCCESS` and `ROWS_WRITTEN > 0` | `SUCCESS` and summed `ROWS_WRITTEN > 0` |
| `STATUS` | status: `SUCCESS`, `FAILED`, `SKIPPED`, `CANCELLED` | `STATUS` | run status |
| `SOURCE_ROWS`, `TARGET_ROWS`, `ROWS_WRITTEN`, `INSERTED`, `UPDATED`, `DELETED`, `REJECTED`, `DUPLICATES` | integer | the task run's counts | summed over the run's task runs |
| `ATTEMPTS` | integer | `ATTEMPT_COUNT` | not available |
| `DURATION_SECONDS` | integer | end minus start | end minus start |
| `ERROR_CLASS` | `TRANSIENT`, `PERMANENT`, `UNKNOWN`, `NONE` | last attempt's failure class | not available |

Status keywords are etl-craft's own (`SUCCESS`, not PowerCenter's `SUCCEEDED`), so a condition, a
status column and the UI use one vocabulary. Today's dependency types map exactly:
`SUCCESS` → `x.SUCCESS`, `FAILURE` → `x.FAILED`, `ALWAYS` → `x.FINISHED`, `HAS_DATA` →
`x.HAS_DATA`; `RUN_CONDITION` `ALL` → `AND`, `ANY` → `OR`, `N` → `AT_LEAST(n, ...)`.

A task that ended `SKIPPED` has counts of 0. A count the handler does not produce (a `PYTHON`
task's `UPDATED`) is NULL; comparing NULL is unknown, and a condition that stays unknown after its
upstream is final is not met, with the reason.

## Evaluation

Conditions use three-valued logic: true, false and unknown, combined the way SQL combines them.
A fact is unknown while the run it reads has not finished, while a failed upstream may still be
retried in this run, and while a cross-pipeline upstream is still running or waiting for a fresh
output. The engine evaluates a task's condition whenever an upstream it names changes state:

- **true:** the task is ready, even if other named upstreams are still running (`a.SUCCESS OR
  b.SUCCESS` starts on the first success, as `ANY` does today);
- **false:** the task is skipped now, with the reason, and its dependents are re-evaluated (as
  `unsatisfiable` does today);
- **unknown:** the task waits.

This replaces `DependencyGraph.ready`, `required_edge_count`, `admission_range` and
`unsatisfiable` with one evaluator over the same run state. Admission of an isolated manual
selection asks the same evaluator with the selected tasks' facts unknown: a condition that is
already decided either way is decided; otherwise the selection waits as today.

`Orchestration.Dependency_gates` keeps its meaning: `warn` runs a task whose condition is false and
records the evaluation as bypassed; `off` evaluates nothing and records every condition bypassed.

**Backfills** assume cross-pipeline upstreams delivered, as today: a cross-pipeline name reads
`STATUS = SUCCESS`, `SUCCESS`, `FINISHED` and `HAS_DATA` true, `FAILED` and `SKIPPED` false, and
every other fact unknown. A backfill whose condition needs another cross-pipeline fact is not met,
with the reason; it does not guess counts.

## Binding names in other pipelines

A name in the same pipeline reads the task run of the same pipeline run. A name in another
pipeline (or project) reads that pipeline's latest finished output that this consumer has not
consumed, under the rules `execution/gates.py` applies today:

1. wait while the upstream's latest run is in progress, within `Orchestration.Gate_wait_minutes`;
2. bind to the latest finished run only if it is newer than what this consumer last consumed (or
   an allowed newer revision); otherwise its facts are unknown and, once the wait budget ends,
   the condition is not met because the upstream has no fresh output;
3. after the consumer succeeds, record the consumed upstream run per edge in
   `AUD_DEPENDENCY_CONSUMPTION`.

`CONSUME_REPAIRS` moves to `CFG_PIPELINES` and applies to every upstream the pipeline's start
condition and its tasks' conditions name. Backfill runs stay invisible to binding.

## Derived edges

`deploy` and re-parse parse every condition and write the names it reads as edges into one
engine-owned table that no team writes, directly or through config files:

```sql
CREATE TABLE CFG_CONDITION_EDGES (
    EDGE_ID                INTEGER PRIMARY KEY,
    PIPELINE_ID            BIGINT NOT NULL REFERENCES CFG_PIPELINES(PIPELINE_ID),
    TASK_ID                BIGINT REFERENCES CFG_TASKS(TASK_ID),           -- NULL: START_CONDITION
    DEPENDS_ON_PIPELINE_ID BIGINT NOT NULL REFERENCES CFG_PIPELINES(PIPELINE_ID),
    DEPENDS_ON_TASK_ID     BIGINT REFERENCES CFG_TASKS(TASK_ID),           -- NULL: a pipeline
    ACTIVE_FLAG            VARCHAR(1) NOT NULL,
    ...audit columns
);
-- one row per (PIPELINE_ID, TASK_ID, DEPENDS_ON_PIPELINE_ID, DEPENDS_ON_TASK_ID)
```

An edge keeps its `EDGE_ID` while some condition still names it, so consumption history continues
across deploys; an edge no condition names any more is set `ACTIVE_FLAG = 'N'`, never deleted,
because consumption and decisions reference it. The scheduler, gates, graphs, catalog, lineage and
impact queries read this table; the pinned definition snapshot carries each condition's text and
parsed form, so a run evaluates the conditions it was admitted with.

`AUD_GATE_DECISIONS` and `AUD_DEPENDENCY_CONSUMPTION` replace `PIPELINE_DEPENDENCY_ID` and
`TASK_DEPENDENCY_ID` with `EDGE_ID`. Each condition evaluation that decides (true, false or
bypassed) adds one row per evaluation to `AUD_GATE_DECISIONS` with the condition text, the values
it read (fact, bound run and value, as JSON) and the result; the per-edge selected upstream run
stays in its own row as today. The task log gets the same line:

```text
condition TRUE for [alpha_prs_to_cdc.SUCCESS AND alpha_preods_delete.SUCCESS]:
alpha_prs_to_cdc.SUCCESS=true (task run 812), alpha_preods_delete.SUCCESS=true (task run 813)
```

## Failing the pipeline

Two task parameters, `Y`/`N`, default `N`, read when the run finishes:

- `FAIL_PIPELINE_IF_FAILED`: the run ends `FAILED` if this task ended `FAILED`;
- `FAIL_PIPELINE_IF_NOT_RUN`: the run ends `FAILED` if this task ended `SKIPPED` because its
  condition was false or could never be met (not when an operator cancelled the run).

Other branches still run to the end; only the run's final status changes, with the reason naming
the task. Without either, the run's status rules are unchanged.

## Refusals

`deploy`, `config plan`, `validate` and re-parse refuse, before anything is written:

```text
tasks.csv line 14: SI_CLIENT_ALPHA.alpha_cdc_to_preods RUN_CONDITION position 24:
value 'alpha_prs_to_cdc.SUCESS'; expected a fact: SUCCESS, FAILED, SKIPPED, FINISHED,
HAS_DATA, STATUS, SOURCE_ROWS, ...; did you mean SUCCESS? correct the condition
```

- unknown task, pipeline or project, with suggestions;
- unknown fact, or a fact unavailable where it is used (`ATTEMPTS` on a pipeline);
- type errors: `x.SUCCESS > 3`, `x.STATUS = 3`, `x.REJECTED = FAILED`, a bare non-boolean fact;
- `AT_LEAST(n, ...)` with `n` below 1 or above the number of conditions;
- a cycle, across pipelines too, named task by task;
- a name in a project the deploying account cannot see;
- a task naming itself, or a pipeline's start condition naming itself.

## Size and slices

About 40 source files read task dependencies and 40 read pipeline dependencies; about 70 test
files build them. S7.BA.2 adds the parser and evaluator in `core` (no database), the derived
table, task conditions and the fail options, and deletes `CFG_TASK_DEPENDENCY`. S7.BA.3 adds
start conditions and deletes `CFG_PIPELINE_DEPENDENCY`. The Support Insights follow-up converts
its 53 task dependency rows (44 `SUCCESS`, 8 `HAS_DATA`); it has no pipeline dependency rows.

Tests: the parser (every rule above, with positions), the evaluator (true, false and unknown for
every fact and operator, retries, cancellation, `AT_LEAST`), the scheduler against today's
dependency suites rewritten as conditions, gates and consumption on SQLite and PostgreSQL, the
refusal messages, and the fail options.

## Owner decisions

1. Status keywords are etl-craft's own: `SUCCESS`, `FAILED`, `SKIPPED`, `CANCELLED`.
2. A condition still unknown when every upstream it names is final is not met: the task is
   skipped with the reason.
3. Each deciding evaluation adds one `AUD_GATE_DECISIONS` row with the condition text and the
   values read as JSON, besides today's per-edge rows.
