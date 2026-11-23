"""Engine DB provisioning and warehouse maintenance, whatever interface requests them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from etl_craft.core.adoption import AdoptResult
from etl_craft.core.errors import ConfigurationError
from etl_craft.engine.migrations import apply_pending_migrations
from etl_craft.engine.privileges import grants_sql
from etl_craft.engine.schema import InitResult, init_db
from etl_craft.services.adopt_target import AdoptRequest, adopt_target
from etl_craft.services.cloning import ClonedTable, clone
from etl_craft.services.lineage import dialect_and_catalog
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import NoInput, Request
from etl_craft.services.rehash import RehashResult as RehashResult
from etl_craft.services.rehash import rehash
from etl_craft.services.setup import SetupResult as SetupResult
from etl_craft.services.setup import setup


@dataclass(frozen=True, kw_only=True)
class InitInput(Request):
    """Whether to recreate an Engine DB that already has tables."""

    force: bool = False


@dataclass(frozen=True, kw_only=True)
class MigrateInput(Request):
    """The project's own migrations directory."""

    migrations_dir: Path | None = None


@dataclass(frozen=True, kw_only=True)
class RehashInput(Request):
    """One existing merge target, as ``schema.table`` or ``database.schema.table``."""

    target: str


@dataclass(frozen=True, kw_only=True)
class AdoptInput(Request):
    """One existing table to adopt; the original is dropped unless ``keep_original``."""

    target: str
    select: str | None = None
    keep_original: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class Clones:
    """Each Engine DB table mirrored into the warehouse."""

    SCHEMA: ClassVar[str] = "etl-craft/clones/1"
    tables: tuple[ClonedTable, ...]


@dataclass(frozen=True)
class Grants:
    """The SQL giving people read-only Engine DB logins, or SQLite's permission note."""

    SCHEMA: ClassVar[str] = "etl-craft/grants/1"
    sql: str


def initialize(ctx: OperationContext, request: InitInput) -> InitResult:
    """Create the Engine DB from the packaged schema."""
    return init_db(ctx.engine, force=request.force)


def migrate(ctx: OperationContext, request: MigrateInput) -> list[str]:
    """Apply pending packaged and project migrations."""
    dialect, catalog = dialect_and_catalog(ctx.config)
    return apply_pending_migrations(
        ctx.engine,
        request.migrations_dir,
        project_default=ctx.config.migrations_dir,
        catalog=catalog,
        warehouse_dialect=dialect,
    )


def clone_tables(ctx: OperationContext, request: NoInput) -> Clones:
    """Mirror the configured Engine DB tables into the warehouse."""
    require_cloning(ctx)
    return Clones(tuple(clone(ctx.engine, ctx.config)))


def require_cloning(ctx: OperationContext) -> None:
    """Require warehouse cloning to be enabled for this project."""
    if not ctx.config.cloning.enabled:
        raise ConfigurationError(
            "Cloning is off in craft-connector.yml: set Cloning.Enabled: true and a Scope of "
            "cfg, aud or all"
        )


def plan_rehash(ctx: OperationContext, request: RehashInput) -> RehashResult:
    """Show the SQL that would publish hash version 2 for an existing merge target."""
    return rehash(ctx.engine, ctx.config, request.target, dry_run=True)


def rehash_target(ctx: OperationContext, request: RehashInput) -> RehashResult:
    """Publish hash version 2 for an existing merge target."""
    return rehash(ctx.engine, ctx.config, request.target, dry_run=False)


def adopt(ctx: OperationContext, request: AdoptInput) -> AdoptResult:
    """Adopt an existing table as its configured writer's target, or show the SQL that would."""
    return adopt_target(
        ctx.engine,
        ctx.config,
        AdoptRequest(request.target, request.select, request.keep_original, request.dry_run),
    )


def setup_engine(ctx: OperationContext, request: NoInput) -> SetupResult:
    """Check the deployment, then create or upgrade its Engine DB."""
    return setup(ctx.config)


def grants(ctx: OperationContext, request: NoInput) -> Grants:
    """Return the SQL giving people read-only Engine DB logins, or SQLite's permission note."""
    if not ctx.config.engine.jdbc_url.startswith("jdbc:postgresql:"):
        return Grants("SQLite uses file permissions; restrict the database file to its owner.")
    return Grants(grants_sql(ctx.config.engine.schema or "public"))
