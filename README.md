# etl-craft

etl-craft is a metadata-driven ETL/ELT engine for moving data. Pipelines, their tasks and the
dependencies between them are rows in the Engine DB. etl-craft reads those rows and runs the work
against one warehouse. The controller schedules and supervises its pipelines.

## Install

Use Python 3.11 or newer. For a local DuckDB warehouse, install the release with:

```bash
pip install 'etl-craft[duckdb]'
```

Use `pip install etl-craft` for PostgreSQL, or select the `trino`, `databricks` or `snowflake`
extra for your warehouse.

Run five example pipelines on SQLite and DuckDB with the
[Quick Start](https://docs.etl-craft.dev/quick-start/).

Operate a server from your own installation without Engine DB or warehouse credentials.
[Remote CLI guide](https://docs.etl-craft.dev/guides/remote-cli/)

[Documentation](https://docs.etl-craft.dev)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributor setup and workflow.

## License

Apache License 2.0. See [LICENSE](LICENSE).
