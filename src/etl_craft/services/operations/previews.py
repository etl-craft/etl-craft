"""Read the first rows of a table the project's catalog lists, for a person who can run its SQL."""

from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from etl_craft.config.targets import active_catalog
from etl_craft.core.errors import (
    ConfigurationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    UsageError,
)
from etl_craft.core.text import is_safe_identifier
from etl_craft.dialects.warehouse.preview import preview_statement
from etl_craft.engine.repository.pipelines import with_suggestions
from etl_craft.handlers.resources import LocalLocker
from etl_craft.services.catalog.collect import collect_catalog
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.permissions import pipeline_access, require_project
from etl_craft.services.operations.requests import Request
from etl_craft.warehouse.connection import open_warehouse

ROWS = 100
"""The most rows a preview returns."""

CELL = 200
"""A value longer than this many characters is cut, with an ellipsis."""


@dataclass(frozen=True, kw_only=True)
class PreviewInput(Request):
    """A table as the catalog names it (``schema.table``), and how many rows to read."""

    table: str
    limit: int = ROWS

    def __post_init__(self) -> None:
        """Refuse an empty name or a row count outside 1 to ``ROWS``."""
        if not self.table.strip():
            raise UsageError("table=''; expected a table the catalog lists, such as ods.orders")
        if not 1 <= self.limit <= ROWS:
            raise UsageError(f"limit={self.limit}; expected 1 to {ROWS}")


@dataclass(frozen=True)
class TablePreview:
    """The first rows of a table, every value as text, with whether more rows exist."""

    SCHEMA: ClassVar[str] = "etl-craft/table-preview/1"
    table: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]
    limit: int
    more: bool


def _cell(value: object) -> str | None:
    if value is None:
        return None
    shown = value.hex() if isinstance(value, bytes | bytearray) else str(value)
    return shown if len(shown) <= CELL else shown[: CELL - 1] + "…"


def preview_table(ctx: OperationContext, request: PreviewInput) -> TablePreview:
    """Read the first rows of a catalog table; only a table the catalog lists is queried."""
    with ctx.engine.connect() as conn:
        require_project(conn, ctx)
        access = pipeline_access(conn, ctx)
    if any(role is None for role in access.roles.values()):
        raise PermissionDeniedError(
            f"project {ctx.project!r}: a table's rows are not tied to one pipeline, but your "
            "access is limited to some pipelines; ask a project manager for whole-project view "
            "access"
        )
    if ctx.config.warehouse is None:
        raise ConfigurationError(
            f"project {ctx.project!r}: no Warehouse is configured, so there are no rows to read; "
            "add a Warehouse section to craft-connector.yml"
        )
    catalog = collect_catalog(ctx.engine, ctx.config, with_warehouse=False, record_lineage=False)
    table = catalog.tables.get(request.table)
    if table is None or table.external:
        known = [name for name, t in catalog.tables.items() if not t.external]
        raise ResourceNotFoundError(
            with_suggestions(
                f"table {request.table!r}: not a table in the project's catalog; a preview reads "
                "only tables the project declares (tables.csv) or that a task reads or writes, "
                "named as the catalog shows them, such as ods.orders",
                request.table,
                known,
            )
        )
    database, schema, name = catalog.where(request.table)
    parts = [part for part in (database or active_catalog(ctx.config), schema, name) if part]
    if not all(is_safe_identifier(part) for part in parts):
        raise UsageError(
            f"table {request.table!r}: {parts!r} needs quoted identifiers, which a preview does "
            "not support; query it with the warehouse's own tools"
        )
    try:
        with (
            open_warehouse(ctx.config, LocalLocker(ctx.engine, ctx.config)) as warehouse,
            warehouse.connect() as conn,
        ):
            statement = preview_statement(".".join(parts), request.limit + 1)
            result = conn.execute(text(statement))
            columns = tuple(map(str, result.keys()))
            fetched = result.fetchmany(request.limit + 1)
    except SQLAlchemyError as error:
        first = str(error).splitlines()[0] if str(error) else error.__class__.__name__
        raise ConfigurationError(
            f"table {request.table!r}: the warehouse refused the preview: {first}; check that "
            "the table exists (the catalog's warehouse comparison says whether it does)"
        ) from error
    return TablePreview(
        request.table,
        columns,
        tuple(tuple(_cell(value) for value in row) for row in fetched[: request.limit]),
        request.limit,
        len(fetched) > request.limit,
    )
