"""Row-level predicates from the mapping's existing sqlglot tree."""

from dataclasses import dataclass

from sqlglot import exp


@dataclass(frozen=True)
class MappingLogic:
    """One condition or output, rendered once and attached to zero or more field rows."""

    expression: str
    columns: tuple[str, ...]
    label: str = ""


def predicates(
    tree: exp.Expr | None, dialect: str | None, *, join: bool = False
) -> tuple[MappingLogic, ...]:
    """Split only AND; OR and multi-column predicates remain one header condition."""
    if tree is None:
        return ()
    if isinstance(tree, exp.And):
        return (
            *predicates(tree.left, dialect, join=join),
            *predicates(tree.right, dialect, join=join),
        )
    columns = tuple(
        dict.fromkeys(column.sql(dialect=dialect) for column in tree.find_all(exp.Column))
    )
    equality = (
        join
        and isinstance(tree, exp.EQ)
        and isinstance(tree.left, exp.Column)
        and isinstance(tree.right, exp.Column)
    )
    attach = columns if not tree.find(exp.Or) and (len(columns) == 1 or equality) else ()
    return (MappingLogic(tree.sql(dialect=dialect), attach),)


def grouping(group: exp.Group, select: exp.Select, dialect: str | None) -> tuple[MappingLogic, ...]:
    """Keep GROUP BY, aggregate outputs and HAVING in one logical stage."""
    rows = [
        MappingLogic(
            item.sql(dialect=dialect),
            tuple(column.sql(dialect=dialect) for column in item.find_all(exp.Column)),
            "Group by",
        )
        for item in group.expressions
    ]
    rows.extend(
        MappingLogic(item.sql(dialect=dialect), (item.alias_or_name,), "Output")
        for item in select.expressions
        if item.find(exp.AggFunc)
    )
    having = select.args.get("having")
    if having is not None:
        rows.extend(predicates(having.this, dialect))
    return tuple(rows)


def rule_predicates(tree: exp.Query, dialect: str | None) -> tuple[MappingLogic, ...]:
    """Read predicates from the qualified rule tree supplied by its lineage trace."""
    where = tree.args.get("where")
    return (
        predicates(where.this, dialect)
        if where is not None
        else (MappingLogic(tree.sql(dialect=dialect), ()),)
    )
