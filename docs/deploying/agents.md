# Agents and the PostgreSQL queue

Set `Deployment.Profile: CONTROLLER_AGENTS` explicitly on the controller and API copies.
PostgreSQL alone does not select cluster execution. `LAPTOP`, `CONTROLLER` and an unset profile
keep local execution, including with a PostgreSQL Engine DB. Cluster mode refuses SQLite.

The controller admits attempts to the queue and monitors them. An attempt without an eligible
agent stays `QUEUED`, naming its pool and slot kind; it never runs on the controller instead.
Each agent runs one process per task and reaches the deployment only through its API. Agents
open no listening ports and need no Engine DB account, URL or credentials.

## Start an agent

Issue a distinct credential for each agent, as an administrator:

```sh
etl-craft token create --name host-a --role agent --pool default --api https://craft.example.com
```

Keep the returned token secret. An agent credential cannot invoke a person's actions, and a
person's credential cannot register, claim, renew or report an agent attempt. Revoking the token
prevents further requests; the agent stops its task processes before their leases expire.

Install the same package version as the API and controller, publish a
[project bundle](project-bundles.md), then start the agent with its bootstrap configuration:

```sh
export ETL_CRAFT_TOKEN="$HOST_A_AGENT_TOKEN"
etl-craft agent --api https://craft.example.com --project-dir /srv/project \
  --pool default --python-slots 4 --warehouse-slots 16
```

`--project-dir` resolves `craft-connector.yml` in that directory. Without it, the normal config
resolution applies, including `--config` and `ETL_CRAFT_CONFIG`.
Execution files are downloaded from the run's pinned publication through the API. The agent
ignores the bootstrap Engine section, which may be absent. Warehouse, Email and Cloning
connections stay in that bootstrap configuration; their credentials must be available through
the agent's configured Secrets provider.
HTTP is accepted only on loopback; use HTTPS elsewhere.

Claims wait up to 30 seconds on notifications. A single session connection on each API copy
serves all claim polls. A missed notification falls back to another queue check within ten
seconds. Renewals run independently of claim polls and log uploads, every ten seconds. The
Engine DB clock governs the 60-second attempt leases. A child also watches its own monotonic
lease deadline and its parent's process birth identity: it stops before lease expiry if the
agent dies or cannot renew. A retry gets a new attempt row; expired ownership is never adopted.

Use `etl-craft agent health` in the same bootstrap directory to check the last successful
renewal. The check needs no API credentials and opens no port. Use a separate writable
bootstrap directory per agent.

## Capacity and controls

The shared resource report measures CPU and memory allocation, reserves and pressure at startup
and on renewals. An explicit Python count can exceed the default memory estimate within measured CPU,
process-base memory and total-slot bounds; warehouse flags remain ceilings.
See [small Python containers](sizing.md#small-python-agent-containers).
Unknown CPU or memory capacity is visible and admits no task. Claims account for reservations
on overlapping allocations on the same host, so two agents cannot count that host twice.
A task must fit one agent; capacity on different hosts is never combined to fit a task.

```sh
etl-craft agents --api https://craft.example.com
etl-craft agent drain --agent-id 12 --api https://craft.example.com
etl-craft agent resume --agent-id 12 --api https://craft.example.com
etl-craft agent stop --agent-id 12 --api https://craft.example.com
```

`drain` stops new claims and completes current tasks; `resume` permits claims again; `stop`
drains and exits. Commands and their acknowledgements are durable. A command for a `GONE` agent
fails by name. SIGTERM drains for `--drain-seconds` (default 300), then stops remaining children
with a failed outcome, `agent drained`. The controller withdraws agents after three missed
heartbeats and reconciles expired attempts as `LOST` before retrying.

The agents service supplies registry status, slot usage and free capacity, running attempts,
resource evidence and pending commands to `agents`, `doctor`, `status` and the API.

## Locks and warehouse statements

Writers to one target, and to a single-writer warehouse, share one lock row in the Engine DB. Its
holder renews it with its lease. A warehouse keeps running a statement after its client dies,
and may still commit it, so a lock left by an ended or expired holder passes only after the next
holder has stopped that holder's statements and confirmed that none still run. Until then the
lock stays with the old holder, and the new writer fails after a bounded wait, naming the target,
the holder and what still runs. Failed work confirms its own statements stopped before
unlocking; a failed confirmation retains the row.

Every warehouse session a holder opens is labelled with it: `application_name` on PostgreSQL,
the client `source` on Trino and `QUERY_TAG` on Snowflake. Scripts must not change these
settings. Attempt labels include an owner or credential namespace, so deployments sharing a
warehouse do not reuse labels. The agent taking over stops the old holder's statements with its own warehouse
credentials. Embedded DuckDB needs no stop: a statement ends with its process. The warehouse
login needs the right to stop its own sessions (PostgreSQL `pg_terminate_backend`, Trino
`kill_query`, Snowflake `SYSTEM$CANCEL_QUERY`).

Databricks requires SQL connector 4.5.0 or newer (installed by the `databricks` extra).
Sessions carry an `etl_craft_holder` query tag. The adapter reads every active
Query History page, cancels matching statement IDs through the Statement Execution API and
confirms that no tagged query remains. The SQL connector's existing authentication is reused;
the warehouse identity needs query-history access and permission to cancel those statements.
Missing permissions, incomplete history or an unconfirmed stop leave the control pending.
Agents never open an Engine DB connection for cancellation.

Operator stop and abort requests wake waiting agent claims through pool and agent notifications.
Renewal remains the fallback when a notification is lost. The agent stops the child and confirms
its tagged warehouse statements ended before reporting a cancellation acknowledgement.

## Connection pooling and shared logs

Ordinary API queries can use PgBouncer transaction pooling. `LISTEN` needs a direct connection
or session-mode pool to the **same Engine DB**:

```yaml
Engine:
  prod:
    Jdbc_url: jdbc:postgresql://pgbouncer:6432/etl_craft
    Listen_jdbc_url: jdbc:postgresql://postgres-rw:5432/etl_craft
    User: etl_craft
    Secret: ENGINE_SECRET
    Schema: public
```

`Listen_jdbc_url` is optional, PostgreSQL only, and changes only the address. It reuses the
profile's authentication; unset, it uses `Jdbc_url`. Both the controller's leadership listener
and API claim listener use this address. At startup, and in `doctor`, a bounded NOTIFY round
trip proves delivery. Failure refuses startup with the masked address and a direct/session-pool
remedy; successfully accepting `LISTEN` alone is insufficient with transaction pooling.

Agents upload bounded ordered log chunks through the API. Their text and hashes remain in the
Engine DB while the attempt runs, so any API copy can serve the live log after another copy
restarts. Identical retries are acknowledged once; changed or out-of-order chunks fail by
attempt and sequence. Every upload is fenced by live attempt ownership. After the outcome
commits, the API publishes these chunks as a file to `Logs.Store` and acknowledges its location
in `LOG_PATH`. Configure `Logs.Profile` explicitly for an S3 store. File stores must be shared
by API/controller copies; agents use only HTTP and need no store credentials.

A `RUN_PIPELINE` handoff has no task-script output: its empty log source commits atomically
with the handoff and can be published while the task waits for its child. Child/control events
remain in the audit run log.

Publication and retention serialize on the exact attempt. A failed upload is a separate audited
failure and leaves the task result and chunks intact; controller maintenance retries even when
daily purge is disabled. Files and chunk rows follow `Retention.Attempt_log_days`. See
[operations](operations.md#logs-and-history) for recovery and backup requirements.

Target writes, target maintenance and the single-writer warehouse queue use one shared durable
resource lock. Its database key is unique; expired or ended holders are replaced atomically.
A wait is bounded and names the target, holder and held duration on timeout. Inspect the holder
before retrying a blocked action.

## Pools, limits and resource placement

Create pools with `etl-craft pool add --name heavy --description "Heavy tasks" --reason "Capacity"`.
Use `pool set --name heavy --description "Updated" --reason "Review"`, `pool list --reason "Review"`,
or `pool disable --name heavy --reason "Retired"`. These are administrator actions. Disable refuses
active project DEFAULT_POOL or active task POOL references and names them; change those first.
Keep `default` available for default projects. Agents must
register in an existing active pool. Set task parameters `POOL`, `CPU_REQUEST` and
`MEMORY_REQUEST_MB`; resource requests are positive whole numbers. Defaults are one CPU and
512 MB for Python, and 0.25 CPU and 128 MB for warehouse work. Gates take no task slots.

`MAX_PARALLEL_TASKS` in `pipelines.csv` limits each pipeline, across its runs and owners.
`PRIORITY` defaults to zero; higher numbers are claimed first and equal priorities use the
oldest queued attempt. A pipeline at its limit is skipped so another can run. Set
`Warehouse.Max_warehouse_queries` to cap warehouse-kind attempts across pipelines and pools.
Only claimed and running attempts count. Limited work stays QUEUED with its reason in
status, explain, the API and its attempt record.

Claims reserve CPU and memory atomically and never combine different agents' capacities.
`validate` rejects requests that fit no active agent in the pool; absent agents leave work
queued. The same check uses measured local allocation when no agents are selected. Local
process and per-kind slot ceilings remain independent of the pipeline limits.

Agent measurements are cgroup-aware and refresh on the existing heartbeat. `--cpu N` and
`--memory-mb N` only lower measured capacity. `--declared-capacity`, with both declarations,
fronts an external quota (for example a script's own runtime); the registry labels it DECLARED.
etl-craft itself launches no external jobs. `--python-slots 0` or `--warehouse-slots 0` makes
an agent single-kind. Slots remain upper bounds alongside CPU and memory.

`agents`, `status`, `doctor` and the API share advertised, reserved and free resources. Draining
withdraws free capacity. Endings, LOST reconciliation and fenced lease expiry release active
reservations. Keep measured-host agents' scopes accurate: overlapping host allocations share
one resource budget.

### Existing token upgrade

Migration 0065 binds each agent token to AUD_AGENTS' latest recorded pool. Unregistered agent
tokens are revoked. Before rotating a token used across pools, list its earlier successful
registrations (the ARGUMENTS document includes each pool):

```sql
SELECT ACTOR, STARTED_AT, ARGUMENTS
FROM AUD_ACTIONS
WHERE COMMAND = 'agent register' AND OUTCOME = 'SUCCESS'
ORDER BY ACTOR, STARTED_AT;
```

The last registered pool is retained; earlier pools do not retain authority. Use a distinct
pool-bound token per agent. Existing token expiry is preserved; `never` in token list means
it needs an explicit rotation policy.

## Project attribution

The API derives a report or log operation's project from its recorded attempt and authenticated
owner, before resolving any project-owned metadata. The agent's bootstrap project and a
client-supplied project name cannot redirect an attempt's writes. The same scope is retained
while asynchronous lock requests wait.

If an existing development Engine DB has agent-created hash contracts under the default
project instead of the intended project, inspect the affected targets and run
`etl-craft --project PROJECT rehash --target TARGET` for each intended merge target before
resuming. Review default-project contracts against that project's own warehouse. There is no
automatic reassignment or deletion of historical contracts.

## Protection reports

The internal `POST /api/v1/agent/report` protocol supports `PROTECTION_READ` and
`PROTECTION_EVENT`. Agents and servers must run the same package version; the normal
protocol-version refusal applies. No extra endpoint, credential, setting or CLI flag is needed.

Each report is bound to its live attempt and fencing credential, its admitted target and
its current Engine DB target lock. Actor and project are derived on the server. An event
contains only kind, key hash, column names, value hashes and status; unknown fields are refused.
PENDING allocates a request id on the server, which the target MERGE stamps on changed rows.
Normal finalization is creator-only. Recovery can finalize a previous attempt's intent only
after that attempt is terminal or reconciled LOST, reporting stamp presence/absence, or
complete keyed-row absence for HARD_DELETE/ERASURE. The status keeps the creator and records
the recovering attempt and actor separately.

Batches contain at most 256 events, with at most 128 column names and corresponding hashes
per event. Oversized lists are refused, never truncated. Reads return at most 256 records
with an event-id cursor; callers follow every page. Both task stores use these same limits
and the same fenced event implementation. Recovery runs where warehouse access exists,
including agents, before mutation and on provenance reads. Controller startup logs an
inaccessible project once and defers its recovery until the next mutation.

Upload-caused PENDING protection reports carry the receipt's `upload_id` as a claim. The server
verifies it against the attempt's run and the successful pinned FILE_VALIDATION task before
storing it; it derives the uploader from AUD_UPLOADS. Upload writes and LOCKED=false UNLOCK
intents share that id. Finalization and recovery retain the original verified id; callers
cannot replace it. Non-upload mutation kinds must omit it. No raw business value is accepted.

Protection reports carry typed warehouse MD5 fingerprints only in transient request bodies.
The host converts them to domain-separated HMAC-SHA-256 identities before audit persistence;
responses and persisted logs never echo those MD5s. `Privacy.Hmac_secret` stays on the host,
including when agent bootstrap and pinned configuration name different secret variables.

`PROTECTION_READ` accepts optional `protection_candidates` only for a PENDING HARD_DELETE or
ERASURE request: its server request id, exact column shape, at most 256 candidate hashes and
an event cursor. The ordinary live-attempt, admitted-target and held-lock fence applies;
the creating attempt must be terminal or reconciled LOST. The host returns matched event
ids for that request and a page cursor, never HMACs or unrelated keys.
The agent scans only non-NULL protection rows, restarts an interrupted scan, and finalizes
only after complete evidence. Stamped writes use the existing request-id recovery path.

## Ending evidence and operator attestation

The parent agent records an observed process exit with the task's admitted PID and birth
identity, separately from confirmed warehouse query absence. This applies to SUCCESS,
FAILED, TIMED_OUT and CANCELLED outcomes. A task-process credential cannot certify its own
exit. Local supervisors use the same evidence rules. Attempt JSON and the attempt page show
process/query evidence kind, actor and reason; migrated old observations remain unclassified.

Agent registration records `ETL_CRAFT_AGENT_INSTANCE_ID` (the pod UID in Kubernetes through
the downward API); a native host process uses its birth and a fresh process instance identity.
Each claim retains the registration identity, so replacing a pod cannot impersonate its exit.
Roll controller, API and agents together after migration 0085.

An old failed, timed-out, cancelled or lost attempt without ending evidence can hold a
timestamp reader's high mark. Successful commits retain their existing window semantics.
Use `reconcile --pipeline-code P --task-code T --reason 'Verified recovery'` first. It verifies
local PID/birth exit and warehouse query absence where possible. If the original pod is gone,
an operator may explicitly attest only its process ending:

```sh
etl-craft reconcile --pipeline-code P --task-code T --attest-ended \
  --reason 'Original pod <name> was deleted; I attest that its task process ended'
```

Attestation requires an expired lease and a terminal/fenced attempt. Ordinary verified
reconciliation of a terminal local worker does not wait for its lease to expire. The warehouse must independently
confirm that no query with its session tag remains. The original instance must not have a
live registration. Legacy claims without an instance column use their recorded hostname and
a later replacement registration; an ambiguous identity is refused. No privileged node or
process-namespace inspection is used. A missing adapter, live query or original instance
refuses the request with a remedy. Stop the original process/queries or restore warehouse
access, then retry; never advance the watermark or edit audit rows to bypass the fence.

Attestation requires the operator role used by reconcile; CAN_RUN alone is insufficient.
The reason is mandatory. Its process row records ATTESTED, actor, reason and the checks that
were verified, while its independently verified query row records VERIFIED. Either explicit
evidence kind releases the same watermark fence. No migration guesses missing evidence.

If the parent's START report loses its API response, the supervisor stops the child and
retains its observed PID/birth and exit. The attempt fails with a START-report message once
the API is reachable; it is not renewed forever as CLAIMED. On an older installation, drain
or replace the owning agent, let its attempt lease expire, reconcile through the documented
verified/attested path, then explicitly retry the failed run. Never edit audit rows.
