"""The statement that previews a table: the same on every supported warehouse."""


def preview_statement(target: str, limit: int) -> str:
    """Return the statement that reads the first ``limit`` rows of ``target``, a checked name."""
    return f"SELECT * FROM {target} LIMIT {limit}"
