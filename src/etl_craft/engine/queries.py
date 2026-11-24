"""Running Engine DB queries from the dialect's query catalog."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import TextClause, bindparam, event, text
from sqlalchemy.engine import Connection, Engine, ExceptionContext

from etl_craft.dialects.engine import for_engine


@event.listens_for(Engine, "handle_error")
def _unwrap_project_selection(context: ExceptionContext) -> None:
    """Re-raise a missing project selection as itself, not as a database statement error."""
    from etl_craft.core.errors import ProjectNotSelectedError

    if isinstance(context.original_exception, ProjectNotSelectedError):
        raise context.original_exception


def statement(bind: Connection | Engine, name: str) -> TextClause:
    """Return catalog query ``name`` for the Engine DB ``bind`` is connected to."""
    from etl_craft.core.definitions import current
    from etl_craft.dialects.engine.definitions import QUERIES

    dialect = for_engine(bind)
    sql = dialect.query(name)
    definition = current.get()
    query = text(sql)
    if definition is not None and name in QUERIES:
        expanded = dialect.admitted_query(sql, definition, name=name)
        if expanded != sql:
            query = text(expanded).bindparams(_admitted_metadata=definition.text)
    if ":project_id" in sql:
        from etl_craft.engine.repository.pipelines import current_project_id, has_selected_project

        # A caller's explicit project_id wins; otherwise the selection is required on execution.
        query = (
            query.bindparams(project_id=current_project_id(f"query {name}"))
            if has_selected_project()
            else query.bindparams(
                bindparam("project_id", callable_=lambda: current_project_id(f"query {name}"))
            )
        )
    return query.execution_options(etl_craft_query=name)


def run_script(conn: Connection, statements: Iterable[str]) -> None:
    """Run each statement exactly as written, with no bind parameters.

    Colons are left alone. A driver whose placeholders use ``%`` (psycopg) still reads one in
    the text as a placeholder, so each ``%`` is doubled for it.
    """
    escape = conn.dialect.paramstyle in {"format", "pyformat"}
    for sql in statements:
        conn.exec_driver_sql(sql.replace("%", "%%") if escape else sql)
