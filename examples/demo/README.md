# Small package demo

Run the [Quick Start](../../docs/quick-start.md) with SQLite, DuckDB and Mailpit.
Persistent views are exercised where the warehouse supports them. DuckDB/Iceberg
uses a table summary and separately asserts the CREATE_VIEW refusal during refresh.
Iceberg fixture cleanup removes both views and tables before deleting its namespaces.

This project is the installed-package contract fixture, with two small Python
sources, offsets, all nine managed SQL actions, business rules, dependency
consumption, alerts, timeouts and stopped-run recovery.

`SOURCE_A` lands two rows per run; `SOURCE_B` lands one. `DEMO` consumes both
sources and fails once at `flaky_feed` before succeeding. `EXPORT` deliberately
exceeds its timeout and SLA. `BACKFILL` supports stopping and resuming a run.
The three reference agents exercise insert, change history, preserved NULL values
and soft deletion; one area label support rule and lineage checks.

The separately loaded `metadata/event_waits.sql` and `python_scripts/delivery.py`
exercise file delivery; the installed tests also check warehouse-row evidence.
Run `etl-craft controller` for server mode after signing in and provisioning a
service token; see the [deployment guide](../../docs/deploying/index.md).

The full domain walkthrough lives in [Support Insights](https://github.com/etl-craft/support-insights).
