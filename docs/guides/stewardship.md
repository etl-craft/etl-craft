# Stewardship uploads

`STEWARDABLE_FLAG=Y` marks a pipeline that accepts files from stewards: it appears in the
upload list, and accounts with `CAN_UPLOAD` on it may send files to it. Otherwise it is an
ordinary pipeline. It can have a schedule, run by hand and depend on other pipelines; an upload
starts or joins a run of it. Developers own its metadata and scripts; stewards supply data using
their existing accounts and pipeline permissions.

Set `STEWARDABLE_FLAG=Y` in `config/pipelines.csv`. Existing pipelines default to `N`.
Grant `CAN_UPLOAD` or higher on the pipeline using the normal permission delegation rules.
`CAN_UPLOAD` sits between `CAN_VIEW` and `CAN_RUN`; on other pipelines it permits viewing only.
There is no steward deployment role. Deployment roles other than admin do not imply a grant.

`FILE_VALIDATION` is an ordinary task handler that checks the files its run carries; any
pipeline that loads files can use it. A pipeline that takes uploads needs exactly one, and
`validate` refuses one without it. Tasks that follow a validation task depend on it with
`HAS_DATA`: the validation task reports the files it accepted as its target count, so in a run
with no files (a scheduled run with nothing uploaded) it succeeds with 0 and the tasks after it
are skipped. `validate` refuses a `SUCCESS` dependency on a validation task.

Set the FILE_VALIDATION task parameter `REQUIRE_UPLOADS=Y` when an upload-free run must fail
instead. It is a Y/N flag, default `N`. With `Y` and no files, validation fails permanently,
without retrying, naming the pipeline/task and telling the caller to start from an upload in
the UI or with `etl-craft upload --pipeline-code <code> <file>`. The attempt and full log retain
that failure; ordinary FAILURE edges can send an alert. Downstream edges remain `HAS_DATA`.
`validate` refuses `REQUIRE_UPLOADS=Y` unless the pipeline has `STEWARDABLE_FLAG=Y`.

Only files the validation task accepted in a real attempt reach later tasks. Marking the
validation task `SUCCESS` does not release a run's files: a task that reads them fails, naming
the upload. Retry or rerun the original upload run to reuse its stored files.

```yaml
Uploads:
  Max_file_mb: 50
```

This blanket limit (`uploads.max_file_mb`) is checked while bytes stream to disk. The validation
task can lower it with `MAX_FILE_MB`. Its other parameters are `SOURCE_EVENT`, `SCRIPT_FILE`, `FILE_FORMAT`
(`CSV`, `TXT`, `XLSX`), optional `ENCODING` (UTF-8), `SHEET_NAME` (first sheet) and JSON
`INPUT_PARAMS`. Text always uses pipes and RFC 4180 quoting. XLSX needs `pip install
'etl-craft[excel]'`; the optional openpyxl dependency is bounded to `>=3.1.5,<4`. Legacy Excel,
macros, excessive ZIP expansion and XML DTDs are refused before the team script runs.

Put the script under `validation_scripts/`:

```python
from etl_craft.scripting import PermanentError, ValidationTask


def validate(task: ValidationTask) -> None:
    rows = task.reader.rows(schema={"LOCKED": bool})
    header = next(rows, None)
    if header not in (("id", "name"), ("id", "name", "LOCKED")):
        raise PermanentError(f"row 1 header={header!r}; expected id|name; upload a corrected file")
    for number, row in enumerate(rows, 2):
        if len(row) != len(header) or not str(row[0]).isdigit():
            raise PermanentError(
                f"row {number} value={row!r}; expected integer id and name; upload a corrected file"
            )
```

`ValidationTask` exposes `upload`, `reader`, `task_params`, `input_params` and `logger`, with no
warehouse connection. Returning None accepts a file; raising refuses it with the recorded
reason. Returning a value is a script defect. The reader streams text or saved workbook values;
a formula without a cached result fails naming its sheet and cell.

```console
etl-craft upload --pipeline-code CORRECTIONS corrections.csv
etl-craft uploads --pipeline-code CORRECTIONS
```

Both commands support `--api`. HTTP clients submit one multipart field named `file` to
`POST /api/v1/uploads?pipeline_code=CORRECTIONS`; GET on the same path lists receipts.
`GET /api/v1/uploads/pipelines` lists active pipelines the caller may upload to. Project-scoped
forms live under `/api/v1/projects/{project}/uploads` too. The API records `AUD_UPLOADS` with
uploader, digest, byte count, timestamps, run, outcome and per-file reason. Duplicate queued or
loaded contents are refused. Client filenames are labels, never storage paths.

The first upload creates an exclusive run. Files arriving during it wait durably; the response
names `waiting_behind_run_id`, with `pipeline_run_id` empty until admission. After that run ends,
the controller takes all pending files into one run in upload-id order, including after restart.
Validation checks each file separately and downstream tasks see only accepted files. If none
passes, the run fails before loading. File retention and restoration are described below.

Python loading scripts read `task.uploads`, retaining every row's `UPLOAD_ID`. Managed SQL writes
must SELECT that column explicitly; `$$upload_ids` expands to bound ids of this run's accepted
files. Set `MERGE_DEDUPE_ORDER=UPLOAD_ID ASC` on stewardship merges. The engine binds the account
for each staged row's upload, refuses missing or foreign ids before mutation, and stamps
`CREATED_BY`/`UPDATED_BY` from that mapping. Landing rows carry `UPLOAD_ID` (and `LOCKED` when used) as ordinary declared columns.
`task.replace_landing` adds no actor columns. Carry `UPLOAD_ID` explicitly through PRS,
CDC and PRE_ODS to each merge. Every upload-bound APPEND_TABLE, OVERWRITE_TABLE and SCD
merge requires UPLOAD_ID in both the SELECT and target, and refuses missing or foreign ids
before mutation. Unprotected APPEND/OVERWRITE staging tables may omit CREATED_BY/UPDATED_BY;
any actor columns they declare are stamped from the upload mapping. Protected targets and
SCD merge targets still require the full audit columns. The next merge binds each account
from UPLOAD_ID even when intervening stages have no actor columns. Later uploads win for overlapping keys.

Optional `LOCKED` controls each USER upload row. Declare it as BOOLEAN in landing, carry it
through the loading script and select it explicitly in the merge SELECT, alongside `UPLOAD_ID`.
TRUE, NULL or an absent column locks as before. FALSE writes the uploaded values without new
locks and releases every existing value lock and the row lock on that key, including an
administrator's locks. A later upload wins, including its control: TRUE after FALSE locks again.
For SCD2, the release follows the current key into later versions. Service-account uploads
create no locks; their FALSE never releases existing locks. `LOCKED` is never stored in the
merge target, compared or hashed; rename any target business column with that name.

`UploadReader.rows(schema={"LOCKED": bool})` checks this optional file column. CSV accepts trimmed,
case-insensitive `true`/`false`, or empty for NULL. XLSX accepts native boolean cells or empty
cells, never strings or numbers. Any other value refuses validation with upload, row, column,
value and remedy. The merge engine requires an actual BOOLEAN SQL column and never parses text:
use `CAST(LOCKED AS BOOLEAN)` in the SELECT or a boolean landing column. Omit the schema argument
for the reader's original untyped values. Only bool schemas are currently supported.

The hash-only event audit retains the verified `UPLOAD_ID` for upload writes and unlocks.
Provenance derives the uploader from its receipt and reports releases as
`upload <id>: LOCKED=false`; it never accepts a caller-supplied uploader or reason.

Stewarded SCD1/SCD2 uploads use in-row human-write protection on every supported warehouse.
Each file's merge writes values, per-cell writers and locks in one target MERGE, then finalizes
its hash-only Engine DB intent before the next file. PostgreSQL before 15 retains its
transactional fallback. See [human overrides](human-overrides.md#atomicity-outside-writers-and-recovery)
for recovery, warehouse permissions and the old-side-table target remedy.

API-only agents fetch bytes through `GET /api/v1/agent/uploads/{upload_id}/content`, passing
`version` and `attempt_id`. Only the owning attempt token with a live lease can read its run's
files. Validation can read every file; downstream attempts cannot read refused files. Local
execution shares the same fenced read function. Both runners stream into a private cache and
verify size and SHA-256 before any script sees the file. No host path or storage credential is
sent to an agent.


## Storage, retention and recovery

An upload streams into `uploads/<PIPELINE_CODE>/.incoming/`, with the size limit and SHA-256
checked as it arrives. The file is flushed and renamed to
`uploads/<PIPELINE_CODE>/<STORED_NAME>` before its audit row and queue/run commit together.
`STORED_NAME` is `<UPLOAD_ID>-<safe name>`, with characters outside `[A-Za-z0-9._-]` replaced
by underscores (an empty label becomes `upload`), truncated to a 255-byte component including
the id prefix. The full original label is retained separately. The stored name is recorded
once and never changed.
The original name remains a label. Folder codes are pinned by the immutable receipt request,
so renaming a pipeline does not strand its earlier files. The CLI history, API and Uploads page show both names.

The API, controller and local runners must see the same project storage directories
(use a shared filesystem when these hosts differ); API-only agents need only the content route.
Only queued files and files of runs that have not ended stay in the pipeline folder. When a
run ends, including failure or cancellation, its files move by same-filesystem rename to
`processed_uploads/<PIPELINE_CODE>/`; later queued files stay put. Folders are created when
needed. Ended attempts' private upload caches are removed too; live attempts keep theirs. A retry inside a run reads its pending files; a rerun of an ended run reads its
processed files. File reads always start from committed audit metadata and check SHA-256.
A missing committed file fails with its upload id, expected locations and the remedy to
upload again. Nothing reconstructs a path from the original client name.

Use the existing retention period and the named archive destination:

```yaml
Retention:
  Run_history_days: 90
Uploads:
  Max_file_mb: 50
  Archive_to: file:///srv/etl-archive/uploads
```

For S3, `Archive_to` uses the same explicit Store/Profile shape as other object locations:

```yaml
Uploads:
  Archive_to:
    Store: s3://team-archive/uploads
    Profile: archive
```

`Object_stores.archive` must exist and name its credential environment variables. No profile
is guessed. The destination is host-owned configuration, including when a run uses a pinned
bundle. `purge` and scheduled retention archive ended uploads older than
`Retention.Run_history_days`; an unset period retains them. A configured period with no
archive destination refuses deletion and names the missing setting. Audit rows and the run's
validation evidence remain available after file archival.

The audit records archive location and time before copying; the timestamp records that durable
archive decision. Copies use `<destination>/<SHA256>/<PIPELINE_CODE>/<STORED_NAME>`. For S3,
the recorded URI also retains the profile name, with no credentials. The local source is
removed only after the archive's size and SHA-256 match. Reruns restore through the shared
local/agent read path, checking the recorded digest before a script sees bytes. An unreachable,
missing or changed archive fails with the upload, location, expected bytes and remedy.

The controller removes uncommitted incoming/final leftovers at startup and logs each removal.
It also finishes committed run-ending moves and archive writes interrupted by a crash; reads
finish the same work. The source survives until its replacement is durable and verified, so
an interrupted archive can leave two copies. A failed commit checks whether the row actually
committed before deleting any bytes or returning an upload id.

Migration 0079 has not shipped in a release and now includes these storage columns and guards.
Development Engine DBs that already applied its earlier form must be recreated; released
versions upgrade through the normal migration path.


## Reference tables seeded from a repository

[Seed tables](seeds.md) load declared files from the pinned project bundle. After a successful
run has taken an accepted upload, the seeds targeted by that run's pinned pipeline version
report `LOCKED`. Future seed changes leave those tables alone and name the original upload
and pipeline. Retargeting today's task does not add or remove a handover; failed and refused
uploads do not create one. Send later corrections through the pipeline's Uploads page.

A seed load runs in-process, with the same target lock and replacement code as `CREATE_TABLE`.
It has its own seed load id and creates no pipeline run. This is separate from row and value
protection and its explicit unlock operations.

## Project privacy secret

Before enabling stewardship protection, name the shared project secret in configuration:

```yaml
Privacy:
  Hmac_secret: ETL_PRIVACY_HMAC
```

Only the variable name is stored. The host resolves it; agents never receive it. Protection
events retain domain-separated keyed identities, not offline-matchable warehouse fingerprints.
Missing or changed secrets are refused by validation, doctor and activation; restore the
original secret because rotation is unsupported in 0.9.0. Erasure shares the secret under
its own domain and overrides human locks. Ordinary hard deletion respects those locks.

Protection covers native PostgreSQL/DuckDB, Trino/Iceberg, DuckDB/Iceberg, Snowflake native
and Iceberg, and Databricks Delta/UniForm. Read the [recovery and permissions contract](human-overrides.md#atomicity-outside-writers-and-recovery),
including deferred controller recovery, doctor findings and the old-target recreation remedy.
[Snapshot retention](erasure.md#human-locks-and-physical-retention) still controls how long
erased values remain readable through time travel; S7.AL.6 owns the outstanding reporting work.

## Files an event wait admits

An ordinary pipeline can validate the files an `EVENT_WAIT` with `EVENT_FILE` admitted in the same
run, with no upload and no uploader. Name the wait in the FILE_VALIDATION task's
`SOURCE_EVENT=<wait task code>`; the validation task must depend on that wait with `SUCCESS`, and
`validate` refuses a name that is not an active file wait of the pipeline. Without `SOURCE_EVENT`
nothing changes: the task validates uploaded files, and every event file reaches later tasks as
before.

With it, the task reads the canonical paths the wait recorded for this run (no other run's
files), checks each with `FILE_FORMAT`, `MAX_FILE_MB`, `ENCODING` and the team script exactly as for
an upload (`task.upload` is the file; its `file_name` and `path` are the event file's), and
records one decision per file in `AUD_EVENT_FILE_DECISIONS`: the SHA-256 and size it read, `ACCEPTED`
or `REFUSED`, and the refusal's reason naming the file. A refused file is never loaded; if every
file is refused the task fails naming the count. A run whose wait admitted nothing succeeds with
0 (so `HAS_DATA` dependents skip), or fails permanently when `REQUIRE_UPLOADS=Y`.

Files the wait admits then reach later tasks (`task.event_files`, `$$event_files`) only after a
successful validation accepted them, whether or not the task depends on it. A task refuses to
start when an accepted file's bytes differ from what validation read, naming the file and both
digests. A retry of the validation keeps the first recorded digest: a file that changed since is
refused, and its latest decision hides it. Deliver a corrected file under a new name. Local and
agent execution use the same checks; an agent reads the file from its own mount of the path.
