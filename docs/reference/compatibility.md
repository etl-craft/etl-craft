# Compatibility policy

The compatibility baseline is **0.9.0**, the first public stable release. Breaking changes
remain possible before that baseline. Version 1.0.0 follows user feedback; it does not reset
the guarantees made at 0.9.0. This follows the recorded
[S7.G owner decision](../development/road-to-1.0.0.md#handover-notes), specifically its
priority correction beginning “Release gate” and “S7.G”; that decision supersedes the
unchanged S7.G item bullets that say “from 1.0.0”.

This page states the release contract, not a claim that unreleased compatibility gates
already pass. The package currently identifies itself as 0.3.0 in
[`pyproject.toml`](https://github.com/etl-craft/etl-craft/blob/main/pyproject.toml).
There are no 0.9.0 or 1.x released schema fixtures yet. Before shipping 0.9.0, the remaining
rolling-version and additive-upgrade checks below must be implemented and demonstrated.

## Versioning and public surfaces

The package uses `MAJOR.MINOR.PATCH`. Patch releases fix defects without breaking contracts;
minor releases add compatible features. Every later 0.x and 1.x release must continue to read
0.9.0 Engine DBs, `craft-connector.yml`, configuration CSVs, CLI invocations, JSON documents
and the version-one HTTP API. **Removal waits until 2.0.0**, after at least one complete minor
release with a warning. Moving from 0.x to 1.0 is not permission to break the 0.9.0 contract.

| Surface | Breaking changes that cannot ship in a compatible release | Compatible evolution and existing evidence |
| --- | --- | --- |
| CLI | Removing/renaming flags or commands, changing accepted values or established meanings/defaults, reassigning exit codes, or changing machine-readable output contracts | Add optional features without changing old invocations. Human-readable text may gain explanation, but promised columns/streams and JSON remain contracts. The parser lives in [`cli/__init__.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/cli/__init__.py) and command modules; [`test_core_errors.py`](https://github.com/etl-craft/etl-craft/blob/main/tests/unit/test_core_errors.py) checks released exit-code numbers and distinct codes per error. |
| HTTP | Removing/changing version-one routes, methods, authorization requirements, request/response fields, types or meanings; adding a required input to an existing request | Keep `/api/v1/` contracts additive; a new major API path does not remove v1 before the package's removal boundary. [`actions.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/services/operations/actions.py) and [`api/routes.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/api/routes.py) supply the registered action/route contract; [`test_action_routes.py`](https://github.com/etl-craft/etl-craft/blob/main/tests/unit/test_action_routes.py) checks their agreement. |
| JSON documents | Removing/renaming fields, changing types or meanings, making optional fields required, or silently changing a document's incompatible shape | Documents identify their contract as `"schema": "etl-craft/<kind>/<n>"`. Add optional response fields; readers tolerate unknown additive output fields. An incompatible document needs a new schema number and retained old readers/contracts until removal is permitted. [`serialization.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/services/operations/serialization.py) emits schema identifiers, rejects mismatches and checks required fields; it is not a complete cross-release test. |
| YAML and configuration CSVs | Removing/renaming keys or columns, changing accepted types/units/default meanings, adding required input without an old-input path, or silently ignoring unsupported input | Old files continue to work. New-only keys, columns and task parameters must be refused by older supported binaries with the required release named, never silently ignored. Current unknown-key checks are in [`loader_helpers.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/config/loader_helpers.py); config-file contracts live in [`services/config_files`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/services/config_files.py). Release-aware refusals still need rolling-compatibility acceptance. |
| Engine DB | Dropping/renaming tables or columns, narrowing types, making an existing column required, or changing meaning so supported older binaries cannot run | Post-0.9 migrations add tables, nullable columns or indexes only. Both dialect schemas/migrations must agree. Existing checks in [`engine/migrations.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/engine/migrations.py) protect the migration ledger and checksums; they do not by themselves prove old binaries run on a new DB. |
| Documented Python contracts | Removing public scripting/configuration/operation names or changing their established signature or behavior | Keep the documented entry points and explicitly exported names; private implementation details are not new promises merely because their source can be browsed. See the [Python API](../api/etl_craft/index.md) and [service-operation guide](../guides/service-operations.md). |

Bug fixes can correct behavior that contradicts a documented contract; their user-visible
impact still belongs in the changelog. Security fixes do not authorize silently reinterpreting
inputs. If a safe fix cannot preserve a promised contract, the maintainer must record the
conflict and obtain an explicit release decision.

## Forward upgrades and rolling operation

Engine DB migrations are forward-only. Every release after the baseline must upgrade every
earlier supported released baseline, including every earlier 1.x release once such releases
exist. There is no promise about nonexistent past 1.x releases and no down-migration path.

The upgrade tests start from the tagged snapshots in
[`tests/fixtures/schemas/`](https://github.com/etl-craft/etl-craft/tree/main/tests/fixtures/schemas),
installed by [`released_schema.py`](https://github.com/etl-craft/etl-craft/blob/main/tests/fixtures/released_schema.py).
[`test_upgrade.py`](https://github.com/etl-craft/etl-craft/blob/main/tests/integration/engine/test_upgrade.py)
checks upgraded structure against fresh initialization and retained data by named columns on
SQLite and PostgreSQL. Released migration files remain immutable; corrections ship forward.

From 0.9.0, rolling upgrades across controller, UI, agent and CLI use declared same-major
compatible ranges and additive API contracts instead of exact-version equality. The explicit
0.9.0-to-1.x baseline guarantee above also holds; “same major” cannot cancel it. Each release
must document its compatible ranges and exercise old/new role combinations and the previous
suite on the upgraded database in the **release gate**, not by repeating suites on every PR.
No untested version range is implied by the Python package's installation metadata.

Post-0.9 migrations must leave supported older binaries usable against the upgraded database.
Rollback is reinstalling a compatible previous binary, **not** reversing the migration.
This additive rule concerns package Engine DB migrations; it does not permit destructive
team metadata edits or warehouse writes without their own controls. New features may need
new settings/columns/parameters, but older binaries must name the release required rather
than guessing or ignoring them. Back up and follow the [deployment guide](../deploying/index.md)
for the installed release.

Current enforcement is intentionally narrower: [`check_agent`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/services/operations/agents.py)
still refuses unequal agent/API versions; [`require_current_schema`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/services/operations/schema_status.py)
requires pending package migrations. These pre-0.9 safeguards are **not** mixed-version
support. Replacing the exact checks with tested ranges, additive migration gates, and
release-aware input refusals remains S7.G work before 0.9.0. Do not use this policy page as
evidence that a current mixed-version deployment is safe.

## Deprecation warnings

A removal announced in a minor release remains available for at least the next complete
minor release with warnings; removal is no earlier than 2.0.0. Every warning names the
surface, replacement/remedy, first deprecated release and earliest removal release. Release
notes and the reference page carry the same information.

| Kind of surface | Where a deprecation warning must appear |
| --- | --- |
| CLI command/flag or exit/output contract | CLI logging at WARNING on standard error when used, keeping JSON/standard output parseable; document exit-code changes before the removal release. |
| HTTP route/request/response field | The affected HTTP response's `Deprecation` header, plus a server operation-log warning; the API reference names the replacement. Do not add warnings to a JSON body's unrelated data fields. |
| JSON schema/field | The consuming CLI's standard-error warning or the HTTP response header/server log, according to transport; Python consumers use `DeprecationWarning` at the documented entry point. |
| YAML key, CSV column or task parameter | The shared loading/validation operation logs WARNING when it encounters the deprecated input: CLI standard error or server logs, plus the configuration reference. |
| Documented Python helper | `DeprecationWarning` at the caller-visible entry point with the replacement named. |
| Engine DB contract | Migration/startup operation logging and release/upgrade notes; retain additive compatibility. A warning is not permission to remove a DB object before 2.0.0. |

This table specifies how future deprecations must be delivered; it does not claim these
channels are already installed on every surface. No new deprecation or warning is introduced
by this documentation change. Current logging/output separation is implemented in
[`core/log.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/core/log.py) and
[`cli/output.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/cli/output.py).

## Supported and tested matrix

Entries below describe the checked-in matrix, not every version a driver might accept.
A code path for an older database does not establish that version as tested. Recheck these
source files for each release; a newer unbounded installer match is not additional test evidence.

| Runtime/Engine DB | Repository-backed coverage | Evidence |
| --- | --- | --- |
| Python 3.11, 3.12, 3.13 | Release matrix on Linux (`ubuntu-latest`) and macOS (`macos-latest`); each runs applicable tests without local services. Linux service suites are separate. Windows is not a supported release-matrix entry. | [Release workflow](https://github.com/etl-craft/etl-craft/blob/main/.github/workflows/release.yml), job `python-platform`; [`pyproject.toml`](https://github.com/etl-craft/etl-craft/blob/main/pyproject.toml) declares `requires-python = ">=3.11"` and these three classifiers. The open-ended lower bound is not a claim of tested Python 3.14+. |
| PostgreSQL 16 | Engine DB and native warehouse local/CI service, including a TLS instance. No wider tested major-version range is inferred. | [`docker-compose.yml`](https://github.com/etl-craft/etl-craft/blob/main/docker-compose.yml) pins both services to `postgres:16`; [CI workflow](https://github.com/etl-craft/etl-craft/blob/main/.github/workflows/ci.yml) starts these services. |
| SQLite supplied with the tested Python runtime | Engine DB suite; no independent SQLite version range is asserted. | [`required-suites.toml`](https://github.com/etl-craft/etl-craft/blob/main/release/required-suites.toml), `engine-sqlite`, and [engine dialect registry](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/engine/__init__.py). |

PostgreSQL before 15 has documented transactional UPDATE/INSERT/DELETE fallbacks rather
than MERGE for protection/erasure. That is version-specific behavior, not evidence of a
second CI PostgreSQL version. PostgreSQL's `pg_input_is_valid` use requires 16 or later.
Sources: [human overrides](../guides/human-overrides.md#atomicity-outside-writers-and-recovery),
[erasure](../guides/erasure.md) and [SQL tasks](../guides/sql-tasks.md).

The warehouse dialect list comes from the
[registry](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/warehouse/registry.py),
[format descriptions](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/warehouse/__init__.py)
and [connection specifications](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/config/auth.py).
Extras and driver constraints are in
[`pyproject.toml`](https://github.com/etl-craft/etl-craft/blob/main/pyproject.toml).

| Warehouse | Tested table format | Installation and coverage evidence |
| --- | --- | --- |
| PostgreSQL | Native | Core psycopg/SQLAlchemy driver; local `warehouse_postgres` and `warehouse-local` CI shard. |
| DuckDB | Native | `duckdb` extra (`duckdb-engine`, `duckdb`); local `warehouse_duckdb` and `warehouse-local` CI shard. |
| DuckDB | Iceberg through the local REST catalog | Same `duckdb` extra; `warehouse_duckdb_iceberg`, `warehouse-iceberg` CI shard. |
| Trino | Iceberg | `trino` extra (`trino[sqlalchemy]`); `warehouse_trino_iceberg`, `warehouse-iceberg` CI shard. Local fixture pins Trino 483 and Iceberg REST fixture 1.10.1 in the compose file. No native Trino format is claimed. |
| Snowflake | Native and Iceberg | `snowflake` extra (`snowflake-sqlalchemy`); credentialed live-cloud `cloud_snowflake` acceptance, outside PR CI. [Iceberg dialect](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/warehouse/snowflake_iceberg.py) defines managed/external volume behavior; writes to externally managed catalogs depend on the integration. |
| Databricks | Delta, and Delta with UniForm readable as Iceberg | `databricks` extra (`databricks-sqlalchemy`, `databricks-sql-connector`, SQLAlchemy constraint); credentialed live-cloud `cloud_databricks` acceptance, outside PR CI. [UniForm dialect](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/warehouse/databricks_iceberg.py) enables Iceberg metadata; this is not a claim of a separate native Iceberg writer. |

Every row's coverage classification is backed by
[`release/required-suites.toml`](https://github.com/etl-craft/etl-craft/blob/main/release/required-suites.toml)
and [`scripts/ci_shards.py`](https://github.com/etl-craft/etl-craft/blob/main/scripts/ci_shards.py).
Snowflake/Databricks have live acceptance suites; availability and results belong to each
candidate's evidence, not a timeless promise that today's cloud credentials/compute work.
DuckDB, PostgreSQL and Trino/Iceberg are covered by local/CI services, not cloud-provider
acceptance. A declared dialect/driver alone does not certify every vendor server release.

## Pre-0.9.0 cleanup inventory and release notes

Before the 0.9.0 public surface freezes, remove aliases, compatibility branches and exports
that have no retained contract or runtime purpose. Do not invent compatibility layers for
unreleased APIs. Once a name becomes a 0.9.0 contract, keep it under the rules above.
The [changelog](https://github.com/etl-craft/etl-craft/blob/main/CHANGELOG.md) separates
Unreleased work from the tagged 0.1.0, 0.2.0 and 0.3.0 release history.

This inventory removes **no public names and no dependencies**. There is no evidence-backed
unused runtime dependency to delete. A repository search cannot establish whether downstream
users call a documented/exported name; lack of an in-repository caller alone does not authorize
breaking it. The following candidate families are retained rather than silently deleted:

| Candidate family | Evidence and disposition |
| --- | --- |
| Pre-project query variants, legacy source/target conversion, account identity conversion | [`engine/queries.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/engine/queries.py), [`migration_steps.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/engine/migration_steps.py), repository conversion modules and the tagged-schema upgrade tests still use them. Retain: removing them changes upgrades from released databases; it needs an owner decision, not an alias purge. |
| Historical configuration reconstruction and old attempt-log paths | [`config_history.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/engine/repository/config_history.py) reconstructs retained history; [`attempt_records.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/execution/attempt_records.py) accepts recorded old paths. Retain: deletion changes historical exports or access to existing logs. |
| `rehash`, `upgrade-targets` and protection's `refuse_legacy` | The released 0.3.0 changelog documents warehouse upgrade commands. [`protection.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/handlers/sql/protection.py) refuses obsolete side tables before writing. Retain: removing these changes an operator contract or a safety refusal. |
| Package/configuration/operation/dialect exports | Explicit `__all__` exports in [`etl_craft`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/__init__.py), [`config`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/config/__init__.py), [`operations`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/services/operations/__init__.py) and both dialect package initializers. All 31 export entries were inventoried; these include active internal callers and documented entry points, not proven unused aliases. `load_config`, `OperationContext`, JSON converters and scripting contracts appear in the Python/service guides. Retain; any public removal needs contract-specific evidence and an owner decision. |
| Exact agent-version and current-schema checks | Retain current pre-0.9 safeguards while the rolling contract is implemented and tested. Deleting a check alone would allow unverified combinations, not implement compatibility. |
| SQL type aliases, PostgreSQL pre-15 fallbacks and SQLite legacy ALTER handling | Warehouse type normalization and dialect-specific data preservation are active database behaviors, not obsolete CLI aliases. Retain; removal changes supported operations or upgrades. |

Earlier CLI/config renamings already removed their aliases, as recorded in Unreleased
changelog entries and [`test_cli.py`](https://github.com/etl-craft/etl-craft/blob/main/tests/unit/test_cli.py).
This inventory does not repeat those removals or claim all public implementation helpers can
safely be deleted. No removal decision for the retained candidates is made here.

The core runtime dependency list is unchanged before and after this inventory:

| Dependency (constraint retained) | Direct runtime role and evidence |
| --- | --- |
| `jinja2>=3.1.6,<4` | Sandboxed email templates: [`handlers/email_templates.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/handlers/email_templates.py). It is not just the removed browser template renderer. |
| `psutil>=6.0,<7` | Resource accounting and process identity: [`core/agent_resources.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/core/agent_resources.py), [`core/resources.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/core/resources.py). |
| `psycopg[binary]>=3.3.6,<4` | Engine DB PostgreSQL connections and leadership: [`controller/leadership.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/controller/leadership.py), [`dialects/engine/postgres`](https://github.com/etl-craft/etl-craft/tree/main/src/etl_craft/dialects/engine/postgres). |
| `pyyaml>=6.0.3,<7` | Connector loading: [`config/loader.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/config/loader.py). |
| `sqlalchemy>=2.0.54,<3` | Engine/warehouse database access: [`dialects/engine/base.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/engine/base.py). |
| `sqlglot>=30.22,<30.23` | SQL parsing and validation: [`dialects/business_rules.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/dialects/business_rules.py). |
| `watchdog>=6,<7` | Runtime file-event observation: [`execution/file_events.py`](https://github.com/etl-craft/etl-craft/blob/main/src/etl_craft/execution/file_events.py). |

Optional drivers/plugins remain extras, not silently promoted into core. Their explicit roles
are warehouse drivers above, `excel` upload/workbook support, `ui` HTTP/browser service and
OIDC cryptography, `aws` object-store integration, and `publish` ngrok hosting, as listed in
[`pyproject.toml`](https://github.com/etl-craft/etl-craft/blob/main/pyproject.toml).
Development/docs packages stay in their dependency groups. **Before = after:** jinja2, psutil,
psycopg, pyyaml, sqlalchemy, sqlglot, watchdog. **Deleted public names: none.**
