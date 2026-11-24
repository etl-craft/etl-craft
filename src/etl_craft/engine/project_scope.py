"""Project selection for configured entry points outside an operation."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from functools import wraps
from typing import Concatenate, ParamSpec, TypeVar

from sqlalchemy.engine import Connection, Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.enums import YesNo
from etl_craft.core.errors import MetadataError, ProjectNotSelectedError, RunStateError
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import has_selected_project, selected_project

P = ParamSpec("P")
R = TypeVar("R")
B = TypeVar("B", bound=Engine | Connection)


def task_run_project_id(bind: Engine | Connection, task_run_id: int) -> int:
    """Return the owning project of the exact task run."""
    with bind.connect() if isinstance(bind, Engine) else nullcontext(bind) as conn:
        project_id = conn.execute(
            statement(conn, "task_run_project"), {"task_run_id": task_run_id}
        ).scalar_one_or_none()
    if project_id is None:
        raise RunStateError(f"no task run with task_run_id={task_run_id}")
    return int(project_id)


@contextmanager
def project_selection(
    bind: Engine | Connection, config: ConnectorConfig, operation: str
) -> Iterator[None]:
    """Keep the caller's selection, or select the connector's explicit, active project."""
    if has_selected_project():
        yield
        return
    if not config.project:
        raise ProjectNotSelectedError(operation)
    with bind.connect() if isinstance(bind, Engine) else nullcontext(bind) as conn:
        project = conn.execute(
            statement(conn, "project_by_code"), {"code": config.project}
        ).one_or_none()
    if project is None or project.active_flag != YesNo.YES:
        raise MetadataError(
            f"project {config.project!r}: expected an active project; "
            "select an active project in Orchestration.Project"
        )
    with selected_project(int(project.project_id)):
        yield


def configured_project(
    call: Callable[Concatenate[B, ConnectorConfig, P], R],
) -> Callable[Concatenate[B, ConnectorConfig, P], R]:
    """Keep the operation's selection, or resolve the explicit connector project."""

    @wraps(call)
    def scoped(engine: B, config: ConnectorConfig, /, *args: P.args, **kwargs: P.kwargs) -> R:
        with project_selection(engine, config, call.__name__):
            return call(engine, config, *args, **kwargs)

    return scoped
