"""``setup``: check a configuration, then create or bring up to date the Engine DB.

Setup first runs ``doctor``'s checks, apart from the Engine DB's tables and migrations, which it
is about to create. If any check fails it stops with nothing changed: every connection the
engine uses must work before it builds anything. Otherwise it creates the Engine DB tables in a
database that has none, then applies the migrations still pending, packaged and the project's
own. On an Engine DB that is up to date it changes nothing, so it can be run again safely.

Setup creates nothing outside the Engine DB's own tables: the Engine DB schema, the warehouse
database and schema, and the email relay must already exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.enums import YesNo
from etl_craft.core.errors import ProjectNotSelectedError, UsageError
from etl_craft.engine.connection import engine_db
from etl_craft.engine.migrations import PROJECT, apply_pending_migrations, migration_streams
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.engine.schema import existing_engine_tables, init_db
from etl_craft.services.doctor import Check, Status, run_checks
from etl_craft.services.lineage import dialect_and_catalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetupResult:
    """What setup checked, and what it did once the checks passed."""

    checks: list[Check]
    created_tables: bool = False
    applied_migrations: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """Whether a check failed, so nothing was changed."""
        return any(check.status is Status.FAIL for check in self.checks)


def require_setup_project(engine: Engine, config: ConnectorConfig) -> None:
    """Refuse unowned project files before setup records or changes anything."""
    if config.project:
        return
    for stream in migration_streams(engine, project_default=config.migrations_dir):
        if stream.source == PROJECT and stream.files:
            raise ProjectNotSelectedError(
                f"setup: {stream.directory} has {len(stream.files)} migration file(s) "
                f"(first: {stream.files[0].version}) that need an owning project"
            )


def setup(config: ConnectorConfig) -> SetupResult:
    """Check the configuration; when nothing fails, create and migrate the Engine DB."""
    checks = run_checks(config, engine_state=False)
    result = SetupResult(checks)
    if result.failed:
        logger.info("setup changed nothing: a check failed")
        return result
    engine = engine_db(config)
    try:
        require_setup_project(engine, config)
        created = not existing_engine_tables(engine)
        if created:
            init_db(engine)
            logger.info("created the Engine DB tables")
        dialect, catalog = dialect_and_catalog(config)
        project_id = None
        if config.project:
            with engine.connect() as conn:
                project = conn.execute(
                    statement(conn, "project_by_code"), {"code": config.project}
                ).one_or_none()
            if project is None or project.active_flag != YesNo.YES:
                raise UsageError(
                    f"setup: project={config.project!r}; expected an active project; "
                    "use an active project or register it with etl-craft project add"
                )
            project_id = int(project.project_id)
        with selected_project(project_id):
            applied = apply_pending_migrations(
                engine,
                project_default=config.migrations_dir,
                package_only=project_id is None,
                catalog=catalog,
                warehouse_dialect=dialect,
            )
        from etl_craft.dialects.engine import for_engine
        from etl_craft.dialects.engine.guards import restore_guards

        with engine.begin() as conn:
            for_engine(engine).refresh_metadata_triggers(conn)
            restore_guards(conn)
        from etl_craft.services.refresh_upgrade import initialize

        refreshed = initialize(engine, config)
        checks.extend(
            Check(
                f"Pipeline refresh {result.pipeline_code}",
                Status.INFO,
                "no version has passed yet; "
                + "; ".join(finding.message for finding in result.findings)
                + "; correct the findings and run `etl-craft pipelines refresh`",
            )
            for result in refreshed.refreshes
            if any(f.failed for f in result.findings)
        )
    finally:
        engine.dispose()
    return SetupResult(checks, created_tables=created, applied_migrations=applied)
