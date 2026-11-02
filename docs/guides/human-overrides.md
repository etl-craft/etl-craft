# Protecting human SCD edits

An authenticated human admin can correct or insert values in an existing SCD1 or SCD2
merge target through the shared service or HTTP API. The first successful edit enables
protection for that target. Ordinary tables keep their existing behavior and may omit actor
columns. Protected SCD targets require their full audit columns, including `CREATED_BY` and
`UPDATED_BY`. `UPLOAD_ID` is read-only file provenance, retained by manual edits; it is not
a business-value lock or an editable value.

## Writers and locks

- A human insert protects the whole business row. A human update protects each changed
  business value; `row_lock: true` also protects the whole row.
- A permitted human can edit a locked value. Its protection remains until an explicit unlock.
- ETL and authenticated service-account integrations create no human locks. They preserve
  existing locks, even when the pipeline was started by a person.
- Row locks prevent ETL updates and SCD2 closure. Any active value or row lock prevents both
  hard and soft deletion. Locks follow the ordered, typed `MERGE_KEY`, across versions.
- Column locks preserve the effective value while other columns change. Hashing and normal
  insert/update counts use the effective values. Input that differs only in a protected value
  creates no new SCD2 version. `PROTECTED_ROWS` and `PROTECTED_VALUES` in the task log report
  prevented changes separately from normal unchanged rows.

SCD1 keeps the original creation attribution. A deliberate SCD2 change closes the previous
version and creates a new attributed version, including edits outside `MERGE_COMPARE_COLUMNS`.
A deliberate edit has no execution run: its affected audit run/task IDs are NULL, and its
warehouse evidence records a unique request ID instead. ETL writes retain their execution IDs.

## HTTP requests

Sign in through the server's [password or SSO flow](../deploying/security.md) and use its
access token as `$ACCESS_TOKEN`. Substitute an existing pipeline, merge task, key and column:

```bash
curl --fail-with-body "$SERVER/api/v1/values" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"pipeline_code":"SALES","task_code":"customers","key":{"customer_id":42},"values":{"name":"Correct name"},"reason":"Verified with customer"}'

curl --fail-with-body "$SERVER/api/v1/values/provenance" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"pipeline_code":"SALES","task_code":"customers","key":{"customer_id":42}}'

curl --fail-with-body "$SERVER/api/v1/values/unlock" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"pipeline_code":"SALES","task_code":"customers","key":{"customer_id":42},"columns":["name"],"reason":"Return ownership to the feed"}'
```

These edit and unlock endpoints require admin. Provenance reads require viewer. Service accounts with admin
may use the write endpoint for automated integrations, with their own identity and no automatic
locks; only USER admins may request a row lock or unlock through these endpoints. A permitted
USER steward can also release row and value locks through an upload with `LOCKED=FALSE`;
[stewardship permissions](stewardship.md) govern those files.

Supply exactly the non-NULL key columns. Key and engine-managed columns cannot be edited.
An insert supplies every business column; an update retains omitted columns. Values are bound
parameters cast to the warehouse's declared types; use ISO strings for dates and timestamps.
Explicit NULL is a value, including when the ETL task uses `PRESERVE_TARGET`. An empty unlock
`columns` list releases every active lock for the key; `"*"` selects just its row lock. Unlock
changes no business data: the next merge may apply source values.

The response schema is `etl-craft/scd-values/1`, containing the target, protection-enabled
state, request ID, current per-column records and at most 100 recent events for the key.
`writer`/`writer_kind` describe the value's writer; `actor` describes the event's requester,
including an unlock. Pre-existing values have an explicitly unknown writer (`null`); actor
strings on the business table are never interpreted as proof. An untracked target returns
`enabled: false`. Evidence remains readable by key after deletion. Upload history includes the
verified `upload_id` and a derived `reason`, including `upload <id>: LOCKED=false` for releases.

## Python service

Use an `OperationContext` holding the authenticated account and current role, as for other
[service operations](service-operations.md):

```python
from etl_craft.services.operations.values import (
    ValueEdit,
    ValueUnlock,
    provenance,
    unlock_values,
    write_values,
)

result = write_values(
    ctx,
    "SALES",
    "customers",
    ValueEdit(
        key={"customer_id": 42},
        values={"name": "Correct name"},
        reason="Verified with customer",
    ),
)
locks = provenance(ctx, "SALES", "customers", {"customer_id": 42})
unlock_values(
    ctx,
    "SALES",
    "customers",
    ValueUnlock(
        key={"customer_id": 42},
        reason="Return ownership to the feed",
        columns=("name",),
    ),
)
```

## Atomicity, outside writers and recovery

Protection lives in each target row: `ETL_PROTECTION` is canonical versioned JSON containing
per-cell writers and locks, `ETL_ROW_FINGERPRINT` hashes the typed business values and that
metadata, and `ETL_PROTECTION_REQUEST_ID` identifies the committing mutation. An SCD1 or SCD2
write changes business values and protection in one target MERGE on PostgreSQL, DuckDB,
Trino/Iceberg, DuckDB/Iceberg, Snowflake and Databricks. PostgreSQL before 15 uses its
same-transaction update/insert fallback. No warehouse side table is authoritative.

Edits, uploads, unlocks, rehash and ETL hold the same Engine DB target lock through commit.
Before the MERGE, `AUD_PROTECTION_EVENTS` records PENDING hash-only intent; after commit it
appends COMMITTED. There are no business values in these events. Each upload file commits its
own mutation before the next file, preserving per-cell attribution for mixed uploaders.
An unchanged cell keeps its actual writer; unlocking changes lock ownership without
inventing a new value writer. Rehash preserves locks and publishes its hash version only
after commit.

Recovery runs before a target mutation, on a provenance read and at controller start. A
request stamp present on a target row proves COMMITTED; no stamp means ABANDONED. For
HARD_DELETE and ERASURE, every affected key must be absent to prove COMMITTED. A live creating
attempt cannot be recovered by another attempt. An expired lease must first be reconciled
LOST. Recovery keeps the creating attempt and request id and records the recovering attempt
and actor separately; repeating it changes nothing.

Pending requests retain their creating attempt's history until recovery resolves them.
After finalization, ordinary run-history retention can remove attempts; the permanent
hash-only event log keeps their original creator/recoverer identifiers.

Agents recover through the fenced internal report protocol, without Engine DB credentials.
Controller startup recovers projects whose warehouse it can open. If it cannot open a
project's warehouse it logs that project once and defers recovery to the next mutation;
it does not fail startup or permit a write without recovery.

Warehouse permissions are the trust boundary. Before a protected operation, fingerprints
detect changed business values or protection metadata, including closed SCD2 history.
Doctor separately reports logged locked-key hashes missing from the target after an outside
deletion, naming the target and remedy. This membership check does not gate writes.
Restrict warehouse write credentials to authenticated integrations; these checks cannot
prevent a warehouse administrator bypassing permissions.

Old targets with `etl_protection_<hash>` or `etl_fingerprints_<hash>` side tables are refused
before any write. Back up the target, recreate it, and re-apply locks through authenticated
edits. There is no conversion action. Back up the Engine DB audit log together with the target.
Restore a consistent backup after detected outside writes. Merge keys, comparison columns and
business shape must match the stored contract. Replacement, append and drop remain refused
for protected targets. Unlocking releases values, not the protection contract.

Fingerprint validation scans all physical versions of an enabled table; account for this
cost when choosing protected targets.


For an existing unprotected merge target from an earlier version, run `etl-craft upgrade-targets`
to add missing engine-managed columns, then `etl-craft rehash` to initialize fingerprints
before enabling protection. This path does not convert a target with old protection side tables.

Protection requires a canonical scalar hash for every business column, including columns
outside `MERGE_COMPARE_COLUMNS`. Ordinary unprotected merges can retain nested columns;
their whole-row fingerprint stays NULL when a business type cannot be hashed. The first edit,
lock or upload is refused before writing that target, naming its column and type: cast the
value to a scalar type in the SELECT. No locked column is omitted from the fingerprint.
`validate` and pipeline refresh report the same problem earlier for declared columns of
stewardable merge targets.

Stewards can also release an existing row lock and all value locks through a USER upload row
with optional BOOLEAN `LOCKED=FALSE`. Its uploaded values still belong to that uploader.
TRUE, NULL or an absent column locks as usual; service-account uploads never release locks.
See [stewardship](stewardship.md) for file validation and landing requirements.
