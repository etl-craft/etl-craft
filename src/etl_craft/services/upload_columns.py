"""Declared merge controls checked without opening the warehouse during validation."""

from collections.abc import Sequence

from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.schema import MappingSchema

from etl_craft.config.targets import active_catalog
from etl_craft.dialects.query_analysis import read_query
from etl_craft.engine.protection_events import target_identity
from etl_craft.engine.repository.source_columns import SourceColumn
from etl_craft.handlers.registry import TaskContext
from etl_craft.handlers.sql import task_dialect
from etl_craft.handlers.sql.spec import SqlTask
from etl_craft.handlers.sql.upload_controls import boolean_problem, target_problem


def problems(context: TaskContext, spec: SqlTask, definitions: Sequence[SourceColumn]) -> list[str]:
    """Refuse reserved target columns and declared nonboolean control projections."""
    target = target_identity(context.config, spec.target_object)[0]
    types = {
        column.column_name: column.data_type
        for column in definitions
        if target_identity(context.config, column.table_name)[0] == target
    }
    result = []
    if problem := target_problem(spec.target_object, types):
        result.append(problem)
    kind = _staged_type(context, spec, definitions)
    if kind and (problem := boolean_problem(f"{context.pipeline_code}.{context.task_code}", kind)):
        result.append(problem)
    return result


def _staged_type(
    context: TaskContext, spec: SqlTask, definitions: Sequence[SourceColumn]
) -> str | None:
    dialect = task_dialect(context).sqlglot_dialect
    root = read_query(spec.select_sql or "", dialect).root
    if not isinstance(root, exp.Query) or (
        not any(c.alias_or_name.lower() == "locked" for c in root.selects)
        and root.find(exp.Star) is None
    ):
        return None
    tables: dict[str, dict[str, str]] = {}
    for column in definitions:
        tables.setdefault(column.table_name, {})[column.column_name] = column.data_type
    schema = MappingSchema(dialect=dialect)
    for table, columns in tables.items():
        schema.add_table(table, columns)
    try:
        assert context.config.warehouse is not None
        typed = annotate_types(
            qualify(
                root.copy(),
                dialect=dialect,
                schema=schema,
                catalog=active_catalog(context.config),
                db=context.config.warehouse.schema,
                validate_qualify_columns=False,
                quote_identifiers=False,
                identify=False,
            ),
            schema=schema,
            dialect=dialect,
        )
    except SqlglotError:
        return "UNKNOWN" if any(c.alias_or_name.lower() == "locked" for c in root.selects) else None
    index = next(
        (i for i, c in enumerate(typed.selects) if c.alias_or_name.lower() == "locked"), None
    )
    if index is None:
        return None
    branches = list(typed.flatten()) if isinstance(typed, exp.SetOperation) else [typed]
    kinds = [
        str(branch.selects[index].type) for branch in branches if isinstance(branch, exp.Query)
    ]
    return "BOOLEAN" if all(kind in {"BOOLEAN", "BOOL"} for kind in kinds) else "|".join(kinds)
