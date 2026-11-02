"""Typed staged upload controls that never become merge target business columns."""

from collections.abc import Mapping

from etl_craft.core.errors import SqlGuardError
from etl_craft.handlers.sql.session import Session


def boolean_problem(task: str, kind: str) -> str | None:
    """Use one strict SQL-type check for validation, refresh and staged rows."""
    if kind.upper() in {"BOOL", "BOOLEAN"}:
        return None
    return (
        f"{task}: staged LOCKED type={kind}; expected BOOLEAN; CAST LOCKED AS BOOLEAN "
        "in the SELECT, or use a boolean column in landing"
    )


def target_problem(target: str, columns: Mapping[str, str]) -> str | None:
    """Reserve the control only on managed merge targets, not on landing tables."""
    if any(c.lower() == "locked" for c in columns):
        return (
            f"{target}: business column LOCKED is reserved for the upload control; "
            "rename the target column and update its declared columns and SELECT"
        )
    return None


def check_stage(session: Session, stage: str, task: str) -> None:
    """Read actual staged types; never parse a string control value in the merge engine."""
    if "locked" not in {c.lower() for c, _ in session.columns(stage)}:
        return
    if problem := boolean_problem(task, session.hash_types(stage)["locked"]):
        raise SqlGuardError(problem)


def check_keys(task: str, keys: tuple[str, ...], compared: tuple[str, ...]) -> None:
    """Keep the control out of stable business identities and comparison hashes."""
    if "locked" in {c.lower() for c in (*keys, *compared)}:
        raise SqlGuardError(
            f"{task}: LOCKED is an upload control, not a business key or comparison column; "
            "remove it from MERGE_KEY and MERGE_COMPARE_COLUMNS"
        )
