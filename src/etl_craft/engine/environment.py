"""Read administrator-managed project identity without inventing an environment."""

from sqlalchemy.engine import Connection

from etl_craft.core.environment import Environment
from etl_craft.core.errors import MetadataError
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import current_project_id


def project_environment(conn: Connection, *, code: str | None = None) -> tuple[str, Environment]:
    """Read the exact current project, including when execution runs through an agent."""
    project_id = current_project_id()
    for row in conn.execute(statement(conn, "project_environment")):
        if code is not None and row.project_code != code:
            continue
        if code is not None or row.project_id == project_id:
            return row.project_code, Environment(row.environment_type, row.environment_name)
    raise MetadataError(
        f"project {code or project_id!r}: missing environment identity; "
        "select a registered project or restore its registration"
    )
