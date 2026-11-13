"""Mapping operators rendered from the lineage parser's existing SQL tree."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlglot import exp

from etl_craft.core.enums_lineage import MappingKind
from etl_craft.handlers.mapping_logic import MappingLogic, grouping, predicates

if TYPE_CHECKING:
    from etl_craft.handlers.lineage import Edge


@dataclass(frozen=True)
class MappingStep:
    """A SELECT operator and its warehouse-dialect expression."""

    kind: MappingKind
    expression: str
    name: str = ""
    logic: tuple[MappingLogic, ...] = ()


def render(node: exp.Expr, dialect: str | None) -> str:
    """Hide only the trace's synthetic default namespace when rendering its SQL."""
    display = node.copy()
    for table in display.find_all(exp.Table):
        if table.catalog == "__etl_craft":
            table.set("catalog", None)
        if table.db == "__unqualified":
            table.set("db", None)
    return display.sql(dialect=dialect)


def steps(tree: exp.Query, dialect: str | None) -> tuple[MappingStep, ...]:
    """Keep aliases, joins and relational operators rather than inferring them from edges."""
    result = [
        MappingStep(MappingKind.SOURCE, render(table, dialect), table.alias_or_name)
        for table in tree.find_all(exp.Table)
    ]
    result.extend(
        MappingStep(
            MappingKind.JOIN,
            render(join, dialect),
            logic=predicates(join.args.get("on"), dialect, join=True),
        )
        for join in tree.find_all(exp.Join)
    )
    result.extend(
        MappingStep(
            MappingKind.FILTER, render(where, dialect), logic=predicates(where.this, dialect)
        )
        for where in tree.find_all(exp.Where)
    )
    for select in tree.find_all(exp.Select):
        group = select.args.get("group")
        if group is not None:
            result.append(
                MappingStep(
                    MappingKind.AGGREGATE,
                    render(group, dialect),
                    logic=grouping(group, select, dialect),
                )
            )
        elif any(item.find(exp.AggFunc) for item in select.expressions):
            result.append(
                MappingStep(MappingKind.AGGREGATE, "", logic=grouping(exp.Group(), select, dialect))
            )
    result.extend(
        MappingStep(MappingKind.SET, render(operation, dialect))
        for operation in tree.find_all(exp.SetOperation)
    )
    return tuple(result)


def parse_select(sql: str, dialect: str | None) -> exp.Query:
    """Read one managed SELECT for column tracing and relational mapping."""
    import sqlglot
    from sqlglot.errors import SqlglotError

    from etl_craft.core.errors import MetadataError

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except SqlglotError as error:
        raise MetadataError(f"the SELECT could not be parsed: {error}; correct its SQL") from error
    if not isinstance(tree, exp.Query):
        raise MetadataError(
            "the statement is not a SELECT; expected a SELECT query; "
            "correct SELECT_QUERY or the SQL file"
        )
    return tree


@dataclass(frozen=True)
class TraceContext:
    """The target and warehouse contract for one parsed SELECT."""

    target: str
    dialect: str | None
    catalog: str | None = None
    schemas: Mapping[str, Mapping[str, str]] | None = None
    cached_edges: tuple[Edge, ...] = ()


@dataclass(frozen=True)
class SelectTrace:
    """One qualified tree and the column edges traced from that same object."""

    tree: exp.Query
    edges: list[Edge]
