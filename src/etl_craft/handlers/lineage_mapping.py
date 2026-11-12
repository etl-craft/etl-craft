"""Mapping operators rendered from the lineage parser's existing SQL tree."""

from dataclasses import dataclass

from sqlglot import exp

from etl_craft.core.enums_lineage import MappingKind


@dataclass(frozen=True)
class MappingStep:
    """A SELECT operator and its warehouse-dialect expression."""

    kind: MappingKind
    expression: str
    name: str = ""


def steps(tree: exp.Query, dialect: str | None) -> tuple[MappingStep, ...]:
    """Keep aliases, joins and relational operators rather than inferring them from edges."""
    result = [
        MappingStep(MappingKind.SOURCE, table.sql(dialect=dialect), table.alias_or_name)
        for table in tree.find_all(exp.Table)
    ]
    result.extend(
        MappingStep(MappingKind.JOIN, join.sql(dialect=dialect)) for join in tree.find_all(exp.Join)
    )
    result.extend(
        MappingStep(MappingKind.FILTER, where.sql(dialect=dialect))
        for where in tree.find_all(exp.Where)
    )
    result.extend(
        MappingStep(MappingKind.AGGREGATE, group.sql(dialect=dialect))
        for group in tree.find_all(exp.Group)
    )
    result.extend(
        MappingStep(MappingKind.AGGREGATE, aggregate.sql(dialect=dialect))
        for aggregate in tree.find_all(exp.AggFunc)
    )
    result.extend(
        MappingStep(MappingKind.SET, operation.sql(dialect=dialect))
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
