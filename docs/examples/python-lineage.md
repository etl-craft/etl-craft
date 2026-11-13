# Declaring an ingestion mapping

A Python `SCRIPT_KIND=INGESTION` task may describe an external source without claiming that
the engine inspected its code. This is documentation only; retries, agents and the script
continue to use the same execution inputs.

The sample `config/task_parameters.csv` uses a table-level `LINEAGE_SOURCE=orders.api` for
`SALES_DAILY.fetch_orders`. No column declarations are needed for that table-level arrow.

For column-level documentation, declare the target columns first. For example, for the sample
`analytics.lnd.orders_uk` target, add this row to `config/columns.csv`:

```csv
CATALOG_NAME,SCHEMA_NAME,TABLE_NAME,COLUMN_NAME,DATA_TYPE,COLUMN_POSITION,IS_NULLABLE,ACTIVE_FLAG
analytics,lnd,orders_uk,order_id,BIGINT,1,N,Y
```

Then add or merge these task-parameter rows by their existing keys:

```csv
PIPELINE_CODE,TASK_CODE,PARAMETER_NAME,PARAMETER_VALUE,ACTIVE_FLAG
SALES_DAILY,fetch_orders,LINEAGE_SOURCE,orders.api,Y
SALES_DAILY,fetch_orders,LINEAGE_COLUMNS,Id:order_id,Y
```

Run `etl-craft config apply`, `etl-craft validate`, then rebuild the catalog. The Mapping tab
shows a **declared** `Id` → `order_id` path. The source name is opaque external documentation;
the target must be an active column of this task's declared target. The engine does not verify
that the Python script actually performs this mapping. Do not put credentials in either parameter.

Remove `LINEAGE_COLUMNS` to return to a table-level declaration. Remove both parameters from
utility scripts and other handlers; validation refuses them there.
