"""Documentation-only ingestion lineage; never invoked by task execution."""

from collections.abc import Mapping

from sqlalchemy.engine import Connection

from etl_craft.core.enums import Handler, ScriptKind
from etl_craft.core.errors import MetadataError
from etl_craft.engine.queries import statement


def columns(params: Mapping[str, str], handler: str, label: str) -> tuple[tuple[str, str], ...]:
    """Validate the declaration grammar independently of a script's implementation."""
    source = params.get("LINEAGE_SOURCE")
    written = params.get("LINEAGE_COLUMNS")
    if source is None and written is None:
        return ()
    problem = None
    if handler != Handler.PYTHON or params.get("SCRIPT_KIND") != ScriptKind.INGESTION:
        problem = "expected a PYTHON SCRIPT_KIND=INGESTION task; remove the lineage parameters"
    elif not source or "." not in source or any(not part.strip() for part in source.split(".", 1)):
        problem = "expected LINEAGE_SOURCE=system.object; declare the external source"
    pairs = (
        tuple(tuple(part.strip() for part in pair.split(":")) for pair in written.split("|"))
        if written is not None
        else ()
    )
    if not problem and any(len(pair) != 2 or not all(pair) for pair in pairs):
        problem = (
            "expected nonempty source_column:target_column pairs separated by |; "
            "correct LINEAGE_COLUMNS"
        )
    if not problem and len({pair[1].casefold() for pair in pairs}) != len(pairs):
        problem = "expected each target column once; remove duplicate LINEAGE_COLUMNS targets"
    if problem:
        raise MetadataError(
            f"task {label}: LINEAGE_SOURCE={source!r}, LINEAGE_COLUMNS={written!r}; {problem}"
        )
    return tuple((pair[0], pair[1]) for pair in pairs)


def validate(
    conn: Connection, task_id: int, params: Mapping[str, str], handler: str, label: str
) -> None:
    """Check declared target names against active metadata, never against executable code."""
    pairs = columns(params, handler, label)
    if not pairs:
        return
    active = {
        row.column_name.casefold()
        for row in conn.execute(statement(conn, "lineage_target_columns"), {"task_id": task_id})
    }
    for _, target in pairs:
        if target.casefold() not in active:
            raise MetadataError(
                f"task {label}: LINEAGE_COLUMNS target={target!r}; expected an active column "
                "of the declared target table; correct the pair or declare the column "
                "in columns.csv"
            )
