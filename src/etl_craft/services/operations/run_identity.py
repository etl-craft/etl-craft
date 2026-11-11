"""Resolve public run references once, before action authorization and execution."""

from dataclasses import replace

from etl_craft.core.errors import ResourceNotFoundError, RunStateError, UsageError
from etl_craft.engine.queries import statement
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.permissions import pipeline_access
from etl_craft.services.operations.requests import RunId, RunIdentity


def resolve_run_reference(ctx: OperationContext, request: object) -> object:
    """Accept integers or exact stored labels, without exposing another project's labels."""
    if not isinstance(request, (RunIdentity, RunId)) or not isinstance(request.run_id, str):
        return request
    value = request.run_id
    numeric = value.isascii() and value.isdecimal()
    suffix = value if numeric else value.rsplit("-", 1)[-1].strip()
    if (
        not suffix.isascii()
        or not suffix.isdecimal()
        or len(suffix) > 19
        or not 1 <= int(suffix) <= 9223372036854775807
    ):
        raise UsageError(
            f"`run_id`={value!r}: expected a positive integer or stored run label; "
            "copy the run id or complete label from history"
        )
    run_id = int(suffix)
    with ctx.engine.connect() as conn:
        row = conn.execute(
            statement(conn, "run_reference"),
            {
                "run_id": run_id,
                "project_id": ctx.project_id,
            },
        ).one_or_none()
        if row is None or not pipeline_access(conn, ctx).permits(row.pipeline_code):
            raise ResourceNotFoundError(
                f"`run_id`={value!r}: expected a visible run in the selected project; "
                "select its project and an authorized run id"
            )
        if not numeric and value != row.run_label:
            raise RunStateError(
                f"`run_id`={value!r}: stored label differs; expected "
                f"{row.run_label!r}; copy this exact case-sensitive label"
            )
    return replace(request, run_id=run_id)
