# Seed tables

Keep small reference tables in the project repository under
`seeds/<catalog>/<schema>/<table>/`. The catalog must match the deployment's warehouse.
Create the warehouse schemas before loading seeds.

Each table folder contains two UTF-8, pipe-delimited files, using the same quoting rules as
[stewardship CSV uploads](stewardship.md). `columns.csv` declares every business column:

```text
COLUMN_NAME|DATA_TYPE|KEY_FLAG
area_code|VARCHAR(100)|Y
area_name|VARCHAR(100)|N
```

`data.csv` starts with the same ordered column names:

```text
area_code|area_name
billing|Billing
technical|Technical support
```

Values are cast by the destination warehouse to their declared types. `validate` checks the selected deployment files and refuses a
missing declaration, a different catalog or an invalid value, naming the file, row, column,
value and remedy. Types are never inferred. Keys must match the merge keys when a pipeline
merges into the table. The seed then receives that merge's audit columns and version-2 hashes.

Publish the files before applying them:

```bash
etl-craft validate --project support
etl-craft config apply --project support
etl-craft bundle publish --project support
etl-craft seed apply --project support
```

`seed apply` requires the developer role and reads the deployment's pinned bundle, including
when called locally. Editing files without publishing does not change what it applies.
`POST /api/v1/projects/{project}/seeds` calls the same operation; `--api` uses that route.
`--format json` returns the `etl-craft/seed-loads/1` document.

The command waits for its in-process loads and reports each table as `LOADED`, `UNCHANGED`,
`LOCKED` or `FAILED`. A SHA-256 of both files decides whether the table changed. A changed
seed replaces the table's rows through the same replacement and recovery code as
`CREATE_TABLE`, under the same target lock as merges. Seeds create no pipeline runs and use
no agent slots. Tables without a stewardship handover remain replaceable.

The first successful pipeline run with an accepted upload locks every seed that its pinned
pipeline tasks target. A failed or refused upload does not lock a seed. Later metadata edits,
including retargeting the task, do not change this recorded handover. Identifiers use the
warehouse's case and quoting rules. Reopening a successful upload run, or failing its repair,
does not unlock its seed: the immutable successful-reopen evidence is retained with the upload.
A locked seed is left untouched, and its message identifies
the upload, date and pipeline whose Uploads page should receive corrections. There is no unlock.

`AUD_SEED_LOADS` retains one append-only, actor-stamped outcome per table per apply, with an
independent `SEED_LOAD_ID`. Failures retain the same masked error message the command reports,
including the table, load id and remedy, without a traceback. `ERROR_MESSAGE` is populated only
for `FAILED`. The command exits 0 for loaded, unchanged and locked tables, and 1 if a table
load failed. Request and validation refusals retain their usual error exit codes.

The [Support Insights demo](https://github.com/etl-craft/etl-craft/tree/main/examples/demo) seeds its reference tables and
includes optional stewardship pipelines to demonstrate the handover on supported warehouses.


Merge-shaped seeds initialize unprotected row metadata and typed fingerprints, so their first
steward upload can establish locks. A nullable `UPLOAD_ID` added by the upload workflow is
file provenance and does not change the protected business contract.
