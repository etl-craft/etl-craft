# etl-craft

A metadata-driven ETL orchestration engine. Pipelines, tasks and their dependencies are rows in
an Engine DB; etl-craft reads that metadata and runs it against one warehouse.
The controller schedules and supervises the work.

Documentation: <https://docs.etl-craft.dev/>

> **0.1.0** is the first release. The previous implementation remains available at the
> `archive/iteration-2` tag; the [changelog](CHANGELOG.md) lists what 0.1.0 holds.

## Try it

PostgreSQL is the default warehouse in the example configuration. For local analytics,
install the DuckDB extra with `pip install etl-craft[duckdb]`.

The [Quick Start](docs/quick-start.md) runs the small package demo (`examples/demo`): five
pipelines on a SQLite Engine DB and a DuckDB warehouse, in about ten minutes. It sends its alerts
to a local Mailpit, which the Quick Start starts with one `docker run`.

```bash
git clone https://github.com/etl-craft/etl-craft.git && cd etl-craft
python -m venv .venv && . .venv/bin/activate
pip install ".[duckdb]"
cd examples/demo
python prepare.py warehouse && etl-craft setup && etl-craft login && python prepare.py metadata
etl-craft run --pipeline-code SOURCE_A --reason "requested data load"
```

Requires Python 3.11 or newer. `uv build` builds the wheel and sdist into `dist/`.

The full walkthrough is developed in the public [Support Insights repository](https://github.com/etl-craft/support-insights).

## Development

```bash
make sync     # create .venv with every dependency group
make check    # lint, format, mypy --strict, layer contracts, history, regressions, quality, tests
make verify-package   # build, then install with pip and uv into clean environments
make docs     # build the documentation site into site/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow and conventions.

## License

Apache License 2.0. See [LICENSE](LICENSE).
