"""The in-row column contract shared by ordinary merges, protected writes and rehash."""

from etl_craft.core.protection_state import RowProtection
from etl_craft.handlers.registry import HandlerResult
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.spec import SqlTask
from etl_craft.handlers.sql.tables import ENGINE_COLUMNS


def business_columns(columns: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Exclude engine-owned fields from the admitted business shape."""
    return tuple(
        c.lower() for c in columns if c.lower() not in ENGINE_COLUMNS and c.lower() != "upload_id"
    )


def contract(task: SqlTask, columns: tuple[str, ...]) -> list[object]:
    """Describe the merge action, keys, comparison and business columns."""
    return [str(task.action), list(task.merge_key), list(task.merge_compare_columns), list(columns)]


def fingerprint(
    session: Session, columns: tuple[str, ...], alias: str, metadata: str, *, preserve: bool = False
) -> str:
    """Hash typed business values together with canonical protection state."""
    types = session.hash_types(session.target)
    values = [f"COALESCE({alias}.{c}, t.{c})" if preserve else f"{alias}.{c}" for c in columns]
    return session.dialect.hash_expression(
        [*values, f"CAST({metadata} AS {session.dialect.string_type})"],
        [*(types[c.lower()] for c in columns), "VARCHAR"],
    )


def baseline(session: Session, task: SqlTask, columns: tuple[str, ...]) -> str:
    """Bind empty protection metadata for an ordinary merge."""
    value = RowProtection(contract(task, columns)).encoded()
    session.bindings["protection_baseline"] = value
    return value


def metadata_result(
    session: Session, stage: str, source: int, rejected: int | None
) -> HandlerResult | None:
    """Keep a same-value row lock from manufacturing a new business version."""
    guard = session.protection
    if guard is None or not guard.request_id or guard.business_changes:
        return None
    guard.metadata_only(stage)
    session.drop(stage)
    return HandlerResult(
        source_count=source,
        target_count=session.count(f"SELECT COUNT(*) FROM {session.target}", step="target rows"),
        insert_count=0,
        update_count=0,
        reject_count=rejected,
    )
