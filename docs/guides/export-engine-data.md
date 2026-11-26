# Export Engine DB data

An ordinary `PYTHON` task can deliver lineage, audit and run data to another system. No
exporter service or OpenLineage integration is required. Use `SCRIPT_KIND=UTILITY`, declare
`SCRIPT_FILE` beneath `python_scripts/`, and return `ScriptResult()` after delivery.

## Choose an existing read path

`ScriptTask` has no Engine DB helper. Agents receive no Engine DB credentials, and there is no
arbitrary named-connection registry in `craft-connector.yml`. A supported direct read path is a
PostgreSQL warehouse in the **same database** as the PostgreSQL Engine DB, using a warehouse
login that already has `USAGE` on the Engine schema and `SELECT` on the source tables. The
warehouse's working schema can differ from the Engine schema; qualify source tables explicitly.
`task.warehouse()` opens the configured warehouse connection locally or on an agent.

Reads are permitted by the Engine's write guards, but they are not exempt from database
privileges. If the warehouse login is the Engine login, its existing grants include these
reads; a separate warehouse login needs an administrator to grant read access first. See
[Engine DB roles](../deploying/engine-db.md) and
[least privilege](../deploying/security.md#least-privilege). Never give an export task owner or
superuser privileges, disable guards, or write source `CFG_`/`AUD_` tables.

With a different warehouse/database, [cloning](../deploying/cloning.md) provides warehouse
mirrors. Enable the required scope (`ALL` for config and audit) and read the explicitly named
mirror schema through `task.warehouse()`. Mirrors reflect the last completed clone, can lag,
and propagate source retention deletions. They are not a permanent export archive. Managed
Engine platforms refuse cloning; use their documented platform read access instead.

## Select a project and explicit columns

The [generated Engine DB schema](../reference/engine-db-schema.md) is the column reference.
There is no general-purpose stable export view. The Engine DB compatibility policy covers
these tables; do not infer that every internal JSON payload in them is a public wire document.
For clients outside a task, the [service operations and JSON guide](service-operations.md)
describes versioned result documents. Never import engine repository internals into a script.

For example, with Engine schema `etl_craft`, bind the intended project ID as `:project_id`
using SQLAlchemy `text` and execute these SELECTs inside `task.warehouse()`:

```sql
SELECT p.PIPELINE_CODE AS pipeline_code, r.PIPELINE_RUN_ID AS pipeline_run_id,
       r.RUN_KEY AS run_key, r.STATUS AS status, r.OUTPUT_REVISION AS output_revision,
       r.START_DATE AS start_date, r.END_DATE AS end_date
FROM etl_craft.AUD_PIPELINES_RUN_LOG r
JOIN etl_craft.CFG_PIPELINES p ON p.PIPELINE_ID = r.PIPELINE_ID
WHERE p.PROJECT_ID = :project_id;

SELECT ACTION_ID AS action_id, STARTED_AT AS started_at, ACTOR AS actor,
       COMMAND AS command, OUTCOME AS outcome, PIPELINE_RUN_ID AS pipeline_run_id
FROM etl_craft.AUD_ACTIONS
WHERE PROJECT_ID = :project_id;

SELECT p.PIPELINE_CODE AS pipeline_code, t.TASK_CODE AS task_code,
       l.TARGET_SCHEMA_NAME AS target_schema, l.TARGET_TABLE_NAME AS target_table,
       l.TARGET_COLUMN AS target_column, l.SOURCE_SCHEMA_NAME AS source_schema,
       l.SOURCE_TABLE_NAME AS source_table, l.SOURCE_COLUMN AS source_column
FROM etl_craft.AUD_COLUMN_LINEAGE l
JOIN etl_craft.CFG_TASKS t ON t.TASK_ID = l.TASK_ID
JOIN etl_craft.CFG_PIPELINES p ON p.PIPELINE_ID = t.PIPELINE_ID
WHERE p.PROJECT_ID = :project_id;
```

Replace `etl_craft` with your configured Engine or mirror schema in reviewed script code;
never interpolate an untrusted identifier. Set `INPUT_PARAMS` to the project ID, such as
`{"project_id": 1}`, and pass `task.input_params["project_id"]` as the bound value. Use
`conn.execute(text(query), {"project_id": project_id}).mappings()` to read named columns.
`AUD_ACTIONS` entries without that project ID are deliberately excluded. Column lineage is the
current re-parsed lineage, not a history of every run's SQL; nullable source columns can
represent expressions with no source column.

Serialize the selected rows into your destination's schema and deliver them with its ordinary
client library. Keep destination credentials in `SECRETS` and read them with `task.secret`.
Page large reads and close read transactions before slow network delivery. Do not export raw
`ARGUMENTS`, metadata snapshots or credentials indiscriminately.

## Make repeat delivery safe

A destination commit and Engine DB task success are separate commits. Upsert snapshots by
Engine DB identity plus `pipeline_run_id` for runs and `action_id` for action records; include
`output_revision` when tracking repaired output versions. Replace the selected project's
current lineage snapshot atomically at the destination. Re-read mutable runs and lineage:
maximum IDs alone cannot detect later updates or deletions. Retention can remove source data,
so arrange delivery before it expires and keep the destination archive independently.

Utility tasks cannot return an offset. Keep any destination checkpoint in the destination's
own transaction; do not edit Engine DB audit rows to record it. A failed delivery must raise,
so the attempt fails visibly. Enable retries only once repeating delivery is safe. An exported
snapshot can include its own task's in-progress run; a later snapshot observes its final state.
