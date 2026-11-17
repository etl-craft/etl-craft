# Personal-data erasure

Register the first warehouse table where the person's identifier enters, usually a landing
or early managed table. Erasure deletes matching rows there and in managed descendants whose
column lineage is a direct pass-through. Renaming a column counts. All SCD2 versions and
matching `<target>__rejects` rows are included. Coverage is computed each time, using the
versions pinned for an ERASURE run; it is never a saved list that can drift.

Set a secret variable through the project's Secrets provider, then name it in
`craft-connector.yml`, after Uploads when present:

```yaml
Privacy:
  Hmac_secret: ETL_PRIVACY_HMAC
```

Only the variable name belongs in the file. Missing or empty secrets refuse erasure before
any deletion. HMAC-SHA-256 covers the normalized table, column and exact key. Protection and
erasure share this project secret with separate HMAC domains. Rotation is not
supported in 0.9.0: an immutable project key check refuses a changed secret before writes or
history lookups. Restore the original secret. Never put its value in configuration.

```bash
etl-craft erase --project support --table raw.people --column customer_id --value KEY --reason 'request received' --dry-run
etl-craft erase --project support --table raw.people --column customer_id --value KEY --reason 'request received'
etl-craft erase --list --project support
etl-craft erase --lift --project support --table raw.people --column customer_id --value KEY --reason 'entry corrected'
```

These commands require admin. The project API uses GET (list) and POST (preview, erase or lift)
at `/api/v1/projects/{project}/erasure`. Administration → Erasure offers a preview of tables,
counts and unfollowed boundaries before confirming the table and column. It never displays the
key. Immediate requests wait for the pass to finish; ordinary ERASURE tasks retain their
normal task timeout. Keep personal values out of shell history and reasons; the private input is not echoed.

Registration commits before deleting. Tables are deleted upstream first, each under its target
lock with one statement or transaction; a crash can leave downstream work pending. Repeating `erase` reapplies its existing active entry without duplicating the register. A later
erasure task repeats all active entries, and deleting an already-cleaned value affects zero
rows. A lift changes the entry from active to inactive once; a second lift fails. Entries are
never deleted. Registering again after a lift adds a new row. A pass snapshots active entries
when it starts; a concurrent lift affects later passes and does not undo committed deletions.

Add an ordinary task with `HANDLER=ERASURE` after loads, or in a nightly data pipeline. It has
no handler-specific parameters. Use task dependencies to place it after every relevant loader.
Every execution reapplies all active project entries, including rows a source has resent.
Its attempt result records table counts keyed by HMAC. Immediate erase is an in-process action,
without an invented pipeline run. Neither path changes the managed write actions.

Erasure shares the guarded hash-only `AUD_PROTECTION_EVENTS` intent log with protected writes
and hard deletes. On capable warehouses it deletes exact matching row identities with one
target MERGE; PostgreSQL before 15 uses a transactional DELETE. In SCD2 history a different
identifier on another version of the same business key is retained. After a crash, recovery
commits a pending deletion only when every recorded affected row identity is absent.

Lineage stops at expressions, hashes, aggregates, surrogate keys and Python writers. Unmanaged
SQL_SCRIPT and team-written targets are reported and never touched. Results, previews and
`doctor` name boundaries and their remedy: keep the identifier out of that table, or register
that table and identifier column as a further entry. A further entry applies independently;
a hash remains a reported lineage boundary. No source system outside the warehouse is
changed. Iceberg tables must support row-level DELETE (format version 2 or later); unsupported
formats or permissions fail with a remedy, without silently rewriting a table.

The raw key is private register data and a bound SQL parameter. Lists, results, errors and logs
use HMACs or masks; SQL never interpolates the key. The private SUBJECT_KEY column is excluded from
Engine DB mirrors. Existing attempt logs are not rewritten. Operation-scoped value masking
protects new erasure operations; broader resolved-secret registration belongs to S7.C. Configure
[log and history retention](../deploying/engine-db.md#retaining-project-history) to bound older
records and archives, and protect database backups and source-system logs separately.

Keep personal data in a few dimension tables and reference them through surrogate keys. This
limits erasure's reach while retaining useful history without distributing personal identifiers.

## Human locks and physical retention

Erasure overrides human row and value locks: removing a person must also remove a steward's
corrected identifier. The lock state disappears with each erased row; permanent keyed events
retain the erasure outcome. Ordinary hard deletion respects those locks instead; unlock the
key before deleting it. Doctor accounts for committed ERASURE and HARD_DELETE events rather
than reporting those keys as outside deletions.

Erasure deletes current rows; it does not remove older versions of a table. On Iceberg tables,
Delta tables (Databricks) and Snowflake tables, erased rows stay readable through time travel
until those versions expire. Erasure never expires snapshots, runs `VACUUM`, restores or rolls
back a table as a side effect.

Each table in an erase result, preview and ERASURE attempt result says where its erased rows
remain (`old_versions`), whether that retention is bounded (`bounded`), and a `retention`
statement naming the bound or how to set one:

| Warehouse | Erased rows remain in | Bound |
|---|---|---|
| Trino over Iceberg | Iceberg snapshots | `SNAPSHOT_RETENTION_DAYS` in `tables.csv`, enforced by `etl-craft purge` |
| DuckDB over Iceberg | Iceberg snapshots | Expire snapshots in the catalog's own maintenance; etl-craft cannot read that bound |
| Databricks (Delta, UniForm) | Delta table history | `delta.deletedFileRetentionDuration` and a scheduled `VACUUM`; etl-craft cannot read that bound |
| Snowflake (native, Iceberg) | Time Travel and Fail-safe | Always bounded by `DATA_RETENTION_TIME_IN_DAYS` (at most 90 days) plus 7 days of Fail-safe |
| PostgreSQL, DuckDB | Nowhere | Deleted rows are not readable through SQL |

`doctor` warns, under **Erasure physical retention**, for each table reached by an active erasure
entry whose old versions have no bound it can confirm, naming the table and the setting to
configure. Removing old versions also needs the warehouse permissions for snapshot expiry or
`VACUUM`; time travel queries need read access to the table. Database backups and source
systems keep their own copies; protect and expire them separately.
