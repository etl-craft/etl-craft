"""The in-row column contract shared by ordinary merges, protected writes and rehash."""

from collections.abc import Mapping

from etl_craft.core.counts import Counts
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.protection_state import RowProtection
from etl_craft.dialects.warehouse import WarehouseDialect
from etl_craft.handlers.registry import HandlerResult
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.spec import SqlTask
from etl_craft.handlers.sql.tables import ENGINE_COLUMNS


def business_columns(columns: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Exclude engine-owned fields from the admitted business shape."""
    return tuple(
        c.lower()
        for c in columns
        if c.lower() not in ENGINE_COLUMNS and c.lower() not in {"upload_id", "locked"}
    )


def type_problems(dialect: WarehouseDialect, target: str, types: Mapping[str, str]) -> list[str]:
    """Check every business value using the same canonical contract as its fingerprint."""
    problems = []
    for column in business_columns(tuple(types)):
        kind = types[column]
        try:
            dialect.canonical_text(column, kind)
        except SqlGuardError:
            problems.append(
                f"{target}, column {column}, type {kind}: protection requires a canonical "
                "scalar hash for every business column; cast it to a scalar type in the SELECT"
            )
    return problems


def contract(task: SqlTask, columns: tuple[str, ...]) -> list[object]:
    """Describe the merge action, keys, comparison and business columns."""
    return [str(task.action), list(task.merge_key), list(task.merge_compare_columns), list(columns)]


def fingerprint(
    session: Session, columns: tuple[str, ...], alias: str, metadata: str, *, preserve: bool = False
) -> str:
    """Hash typed business values together with canonical protection state."""
    types = session.hash_types(session.target)
    values = [f"COALESCE({alias}.{c}, t.{c})" if preserve else f"{alias}.{c}" for c in columns]
    return typed_fingerprint(
        session.dialect, session.target, {c: types[c] for c in columns}, values, metadata
    )


def typed_fingerprint(
    dialect: WarehouseDialect,
    target: str,
    types: Mapping[str, str],
    values: list[str],
    metadata: str,
) -> str:
    """Leave unsupported unactivated targets un-fingerprinted; activation refuses them."""
    if type_problems(dialect, target, types):
        return "NULL"
    return dialect.hash_expression(
        [*values, f"CAST({metadata} AS {dialect.string_type})"],
        [*types.values(), "VARCHAR"],
    )


def baseline(session: Session, task: SqlTask, columns: tuple[str, ...]) -> str:
    """Bind empty protection metadata for an ordinary merge."""
    value = RowProtection(contract(task, columns)).encoded()
    session.bindings["protection_baseline"] = value
    return value


def metadata_result(session: Session, stage: str, counts: Counts) -> HandlerResult | None:
    """Keep a same-value row lock from manufacturing a new business version."""
    guard = session.protection
    if guard is None or not guard.request_id or guard.business_changes:
        return None
    guard.metadata_only(stage)
    session.drop(stage)
    return HandlerResult(
        source_count=counts.source_count,
        target_count=session.count(f"SELECT COUNT(*) FROM {session.target}", step="target rows"),
        insert_count=0,
        update_count=0,
        reject_count=counts.reject_count,
        duplicate_count=counts.duplicate_count,
    )
