# Catalog document, shape 2

`generate-docs` writes `catalog.json` beside the static HTML from the catalog model.
The app reads it through `CATALOG_PAGE` with `path=catalog.json`, using the existing project
access check. No additional API action, setting, table or persistence format is introduced.
`schema` is `etl-craft/catalog/2`; pre-0.9 shape 1 is replaced without an adapter. Rebuild
old catalog folders after upgrading.

The root retains `generated_at`, `compared_at`, `project`, `environment`, `database`,
`sql_dialect`, `warehouse`, `contract_version`, and the asset collections `pipelines`,
`tasks`, `tables`, `rules`, `scripts`, `table_edges`, `column_edges`, `triggers` and `gaps`.
`definition_edges` contains `kind` (`task` or `pipeline`), `source`, `target`,
`dependency_type` and `consume_repairs`. `gate_wait_minutes` records the deployment's budget.

Each pipeline includes its schedule, auto-restart condition, refresh type, SLA, tags, paused
state, tasks and recent runs. `upstream`, `downstream` and `gates` carry typed pipeline edges;
gates add the wait budget. `triggers` identifies configured triggering tasks and their mode and
wait timeout. Root `triggers` retains recorded run-trigger history.

Each task includes its handler, script kind, run condition and count, active and target-active
flags, effective retries, timeout in seconds and retry-on policy, and `secrets` containing
**variable names only** for Python tasks. It retains documentation, target, sources,
dependencies, rules and recent run summaries. `gate` describes event-wait polling and timeout.
No secret provider is queried to build this document.

`lineage` replaces `lineage_error`: `{state, reason}`, where state is `derived`, `declared`
or `unavailable`. Declared lineage comes only from `LINEAGE_SOURCE` and optional
`LINEAGE_COLUMNS` on Python INGESTION tasks. The parameters document code; execution never
uses or verifies them. Intentional limitations are neutral information, not lineage gaps.
Managed SELECT parse/resolution failures remain actionable gaps.

`mapping` holds `steps` (`kind`, warehouse-rendered `expression`, source alias `name`, and
`logic` rows with `expression`, `columns` and `label`),
`edges` (target object/column, source object/column, transformation, task), `source` for a
declared external source and `write` (SQL action, keys and engine-managed column names). A direct SQL column copy has
transformation `copy`. A declared edge has transformation `declared`. Target types and
nullability come from the table's column collection. Rule metadata includes its SQL expression.
An edge with no source object/column has no direct column input; it is not assumed to be a
literal constant. The diagram can show its parsed table row-set context without inventing a
source column. All of these are snapshots of the build; generating a catalog does not run the pipeline.

`logic` receives the same qualified sqlglot tree used by the column trace. It never parses
SQL itself. Rule placeholders are expanded only by the existing shared business-rule scope
expander before tracing the rule SELECT. Filter/HAVING conditions split only at AND;
one-column predicates attach to field rows, while OR and cross-column conditions have no
row attachment. Join equality keys attach to both key columns. Group-by rows carry the
"Group by" label, aggregate outputs carry "Output", and rules retain their predicate rows.
The table representation includes every condition once, even if a join key is shown twice
in the diagram. No browser SQL parser is used.
