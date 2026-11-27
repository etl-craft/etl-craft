"""Remove execution details of restricted related pipelines from operation documents."""

from dataclasses import fields, is_dataclass, replace

from sqlalchemy.engine import Connection

from etl_craft.core.conditions import Scope, parse
from etl_craft.core.enums import ApiRole
from etl_craft.engine.queries import statement
from etl_craft.services.lineage import Edge, TaskLineage
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.diagnostics import LineageView
from etl_craft.services.operations.models import GraphView, GridCell, RunView, StepView, TaskRunView
from etl_craft.services.operations.permissions import PipelineAccess, pipeline_access
from etl_craft.services.operations.status import DependencyView, Explanation


def visible_result(ctx: OperationContext, result: object) -> object:
    """Keep related pipeline names while withholding their tasks and run identities."""
    if ctx.role == ApiRole.ADMIN or not is_dataclass(result):
        return result
    with ctx.engine.connect() as conn:
        return _visible(conn, ctx, pipeline_access(conn, ctx), result)


def _run_allowed(conn: Connection, access: PipelineAccess, run_id: int | None) -> bool:
    if run_id is None:
        return False
    code = conn.execute(statement(conn, "api_run_code"), {"run_id": run_id}).scalar_one_or_none()
    return code is not None and access.permits(code)


def _visible(
    conn: Connection, ctx: OperationContext, access: PipelineAccess, value: object
) -> object:
    if isinstance(value, DependencyView):
        return _dependency_view(conn, ctx, access, value)
    if (
        isinstance(value, (Explanation, StepView))
        and value.run_condition
        and not _condition_visible(conn, ctx, access, value.run_condition)
    ):
        message = "Related pipeline condition requires project and pipeline CAN_VIEW."
        value = replace(value, run_condition=message)
    if isinstance(value, (TaskLineage, Edge)):
        label = value.task
        if label and not access.permits(label.partition(".")[0]):
            if isinstance(value, TaskLineage):
                return TaskLineage(label.partition(".")[0], None, [], sources=())
            return replace(value, task=label.partition(".")[0], transformation="")
    if isinstance(value, (RunView, TaskRunView)):
        children = tuple(i for i in value.child_run_ids if _run_allowed(conn, access, i))
        value = replace(value, child_run_ids=children)
        if isinstance(value, RunView) and not _run_allowed(conn, access, value.parent_run_id):
            value = replace(value, parent_run_id=None, triggered_by_task_run_id=None)
    if isinstance(value, LineageView):
        value = replace(
            value,
            upstream_tables=tuple(
                (depth, table, _related_label(access, task))
                for depth, table, task in value.upstream_tables
            ),
            downstream_tables=tuple(
                (depth, table, _related_label(access, task))
                for depth, table, task in value.downstream_tables
            ),
        )
    if isinstance(value, GraphView):
        value = replace(
            value,
            depends_on={
                task: tuple(
                    (
                        _related_label(access, label),
                        kind,
                    )
                    for label, kind in dependencies
                )
                for task, dependencies in value.depends_on.items()
            },
        )
    return _visible_children(conn, ctx, access, value)


def _visible_children(
    conn: Connection, ctx: OperationContext, access: PipelineAccess, value: object
) -> object:
    if is_dataclass(value) and not isinstance(value, (type, GridCell)):
        return replace(
            value,
            **{f.name: _visible(conn, ctx, access, getattr(value, f.name)) for f in fields(value)},
        )
    if isinstance(value, tuple):
        return tuple(_visible(conn, ctx, access, item) for item in value)
    if isinstance(value, list):
        return [_visible(conn, ctx, access, item) for item in value]
    if isinstance(value, dict):
        return {key: _visible(conn, ctx, access, item) for key, item in value.items()}
    return value


def _related_label(access: PipelineAccess, label: str) -> str:
    """Keep the related pipeline name, without a task the account cannot view."""
    return (
        label
        if "." not in label or access.permits(label.partition(".")[0])
        else label.partition(".")[0]
    )


def _condition_visible(
    conn: Connection, ctx: OperationContext, access: PipelineAccess, rule: str
) -> bool:
    return all(
        len(ref.parts) == 1 or _can_view_related(conn, ctx, access, ref.parts, len(ref.parts) == 3)
        for ref in parse(rule, Scope.TASK).refs
    )


def _can_view_related(
    conn: Connection,
    ctx: OperationContext,
    access: PipelineAccess,
    parts: list[str] | tuple[str, ...],
    cross: bool,
) -> bool:
    if not cross:
        return access.permits(parts[0])
    row = conn.execute(statement(conn, "project_by_code"), {"code": parts[0]}).one_or_none()
    scoped = None if row is None else replace(ctx, project=parts[0], project_id=row.project_id)
    return scoped is not None and pipeline_access(conn, scoped).permits(parts[1])


def _dependency_view(
    conn: Connection, ctx: OperationContext, access: PipelineAccess, value: DependencyView
) -> DependencyView:
    """Retain recorded decisions without disclosing inaccessible upstream execution details."""
    if value.pipeline_dependency_id is None and value.task_dependency_id is None:
        return value
    parts = value.upstream.split(".")
    cross = (value.pipeline_dependency_id is not None and len(parts) > 1) or (
        value.task_dependency_id is not None and len(parts) > 2
    )
    if _can_view_related(conn, ctx, access, parts, cross):
        return value
    return replace(
        value,
        upstream=".".join(parts[:2]) if cross else parts[0],
        status=None,
        reason="Related pipeline details require project and pipeline CAN_VIEW.",
        task_dependency_id=None,
        pipeline_dependency_id=None,
        selected_pipeline_run_id=None,
        selected_task_run_id=None,
        selected_revision=None,
        selected_run_label="",
        selected_task_run_label="",
    )
