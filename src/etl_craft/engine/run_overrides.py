"""Immutable run inputs over the recorded executable definition."""

import json
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.engine import Connection

from etl_craft.core.actor import current_actor
from etl_craft.core.definitions import Definition
from etl_craft.core.errors import RunStateError
from etl_craft.engine.queries import statement


def recorded(conn: Connection, run_id: int) -> dict[str, dict[str, str]]:
    """Read only the exact run's immutable input record."""
    value = conn.execute(statement(conn, "run_overrides"), {"run_id": run_id}).scalar_one_or_none()
    return {} if value is None else json.loads(value)


def from_snapshot(
    snapshot: str, run_id: int, bundle_id: str | None, overrides: str | None, pipeline_id: int
) -> Definition:
    """Decode the base and its joined override record through one effective-value path."""
    return effective(
        Definition.read(snapshot, run_id, bundle_id),
        {} if overrides is None else json.loads(overrides),
        pipeline_id,
    )


def effective(
    definition: Definition, values: dict[str, dict[str, str]], pipeline_id: int
) -> Definition:
    """Overlay existing task parameters without changing the base image or current config."""
    if not values:
        return definition
    rows = dict(definition.rows)
    tasks = {
        str(row["task_code"]): row["task_id"]
        for row in rows["CFG_TASKS"]
        if row["pipeline_id"] == pipeline_id
    }
    changes = {}
    for task, params in values.items():
        if task not in tasks:
            raise RunStateError(
                f"override task {task!r}: missing from pinned definition; start a "
                f"new run with compatible inputs"
            )
        for name, value in params.items():
            changes[tasks[task], name] = value
    parameters = []
    for row in rows["CFG_TASK_PARAMETERS"]:
        key = (row["task_id"], row["parameter_name"])
        parameters.append({**row, "parameter_value": changes.pop(key)} if key in changes else row)
    if changes:
        raise RunStateError(
            f"override parameters {list(changes)!r}: missing from pinned "
            f"definition; use existing task inputs"
        )
    rows["CFG_TASK_PARAMETERS"] = tuple(parameters)
    image = json.loads(definition.text)
    image["CFG_TASK_PARAMETERS"]["rows"] = parameters
    return replace(definition, rows=rows, text=json.dumps(image, sort_keys=True))


def store(
    conn: Connection,
    run_id: int,
    project_id: int,
    key: str | None,
    digest: str,
    values: dict[str, dict[str, str]],
) -> None:
    """Commit actor-attributed overrides in the run-admission transaction."""
    actor = current_actor()
    conn.execute(
        statement(conn, "run_overrides_insert"),
        {
            "run_id": run_id,
            "project_id": project_id,
            "request_key": key,
            "request_digest": digest,
            "overrides": json.dumps(values, sort_keys=True),
            "actor": actor.name,
            "actor_kind": actor.kind,
            "now": datetime.now(UTC),
        },
    )
