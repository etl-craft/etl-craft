"""Validate a full reference correction before its ingestion task can read it."""

from etl_craft.scripting import PermanentError


def validate(task):
    """Refuse malformed headers, widths and reference keys before ingestion."""
    expected = tuple(task.input_params["columns"])
    rows = task.reader.rows()
    header = next(rows, None)
    if header != expected:
        raise PermanentError(
            f"row 1 header={header!r}; expected {expected}; upload a corrected pipe-delimited file"
        )
    seen = set()
    for number, row in enumerate(rows, 2):
        if len(row) != len(expected) or not row[0] or row[0] in seen:
            raise PermanentError(
                f"row {number} value={row!r}; expected {len(expected)} fields and a unique "
                "nonempty key; upload a corrected file"
            )
        seen.add(row[0])
