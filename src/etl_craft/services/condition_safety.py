"""Report broken inbound condition edges without resolving other projects' expressions."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Connection

from etl_craft.engine.queries import statement

PipelineVisibility = Callable[[Connection], set[int]]


@dataclass(frozen=True)
class BrokenCondition:
    """A local upstream and the diagnostic safe to show to the caller."""

    upstream: str
    message: str


def broken_conditions(
    conn: Connection, project_id: int, project: str, visibility: PipelineVisibility | None
) -> list[BrokenCondition]:
    """Inspect active inbound edges and redact dependent names before returning findings."""
    by_upstream: dict[str, list[str]] = defaultdict(list)
    hidden: dict[str, int] = defaultdict(int)
    rows = [
        row
        for query in ("broken_inbound_task_conditions", "broken_inbound_start_conditions")
        for row in conn.execute(statement(conn, query), {"project_id": project_id})
    ]
    visible = visibility(conn) if rows and visibility is not None else set()
    for row in rows:
        upstream = row.upstream_pipeline
        if row.upstream_task is not None:
            upstream += "." + row.upstream_task
        if row.downstream_pipeline_id not in visible:
            hidden[upstream] += 1
        else:
            downstream = f"{row.downstream_project}.{row.downstream_pipeline}"
            if row.downstream_task is None:
                by_upstream[upstream].append(f"{downstream} START_CONDITION")
            else:
                by_upstream[upstream].append(f"{downstream}.{row.downstream_task} RUN_CONDITION")
    return [
        BrokenCondition(
            upstream,
            _message(f"{project}.{upstream}", by_upstream[upstream], hidden[upstream]),
        )
        for upstream in sorted(by_upstream.keys() | hidden.keys())
    ]


def _message(upstream: str, dependents: list[str], hidden: int) -> str:
    parts = [f"upstream {upstream}: ACTIVE_FLAG=N; expected an active condition target"]
    if dependents:
        verb = "depends" if len(dependents) == 1 else "depend"
        parts.append(
            f"{', '.join(sorted(dependents))} {verb} on {upstream}; "
            "change the downstream condition or deactivate its owner first"
        )
    if hidden:
        other = "a task in another project" if hidden == 1 else f"{hidden} tasks in other projects"
        verb = "depends" if hidden == 1 else "depend"
        parts.append(f"{other} {verb} on {upstream}; ask an administrator")
    return "; ".join(parts)
