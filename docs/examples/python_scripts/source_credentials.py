"""Read declared provider credentials without embedding them in metadata."""

from etl_craft.scripting import ScriptResult


def run(task):
    """Use SECRETS=SOURCE_PASSWORD and configure the host provider before running."""
    password = task.secret("SOURCE_PASSWORD")
    task.logger.info("source credential is configured: %s", bool(password))
    return ScriptResult(0)
