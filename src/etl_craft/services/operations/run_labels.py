"""Attach stored display labels to visible operation results without changing their identities."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace

from sqlalchemy import bindparam

from etl_craft.engine.queries import statement
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.permissions import pipeline_access

PAIRS = {
    "pipeline_run_id": "run_label",
    "run_id": "run_label",
    "task_run_id": "task_run_label",
    "parent_run_id": "parent_run_label",
    "child_run_ids": "child_run_labels",
    "triggered_by_task_run_id": "triggered_by_task_run_label",
    "execution_run_id": "execution_run_label",
    "waiting_behind_run_id": "waiting_behind_run_label",
    "pending_task_run_id": "pending_task_run_label",
    "selected_pipeline_run_id": "selected_run_label",
    "selected_task_run_id": "selected_task_run_label",
    "released_pipeline_run_ids": "released_pipeline_run_labels",
}


OPAQUE = frozenset(
    {"arguments", "before_json", "after_json", "parameters", "row_key", "rows", "key", "values"}
)


def _records(value: object) -> list[Mapping[str, object]]:
    if is_dataclass(value) and not isinstance(value, type):
        record = {f.name: getattr(value, f.name) for f in fields(value)}
        return [
            record,
            *(row for key, child in record.items() if key not in OPAQUE for row in _records(child)),
        ]
    if isinstance(value, Mapping):
        return [
            value,
            *(row for key, child in value.items() if key not in OPAQUE for row in _records(child)),
        ]
    if isinstance(value, (list, tuple)):
        return [row for child in value for row in _records(child)]
    return []


def with_run_labels(ctx: OperationContext, result: object) -> object:
    """Batch-read labels after visibility filtering; never derive them from mutable timestamps."""
    records = _records(result)
    if ctx.project_id is None or not any(any(key in row for key in PAIRS) for row in records):
        return result
    labels: dict[str, dict[int, str]] = {"run": {}, "task": {}}
    with ctx.engine.connect() as conn:
        access = None
        for kind, query in (("run", "display_run_labels"), ("task", "display_task_run_labels")):
            ids: set[int] = set()
            for row in records:
                for key in PAIRS:
                    if ("task" in key) != (kind == "task"):
                        continue
                    value = row.get(key)
                    ids.update(
                        v
                        for v in (value if isinstance(value, (list, tuple)) else [value])
                        if isinstance(v, int)
                    )
            if not ids:
                continue
            access = access or pipeline_access(conn, ctx)
            for stored in conn.execute(
                statement(conn, query).bindparams(bindparam("ids", expanding=True)),
                {"ids": sorted(ids), "project_id": ctx.project_id},
            ):
                if access.permits(stored.pipeline_code):
                    labels[kind][stored.id] = stored.label
    return _labelled(result, labels)


def _labelled(value: object, labels: dict[str, dict[int, str]]) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        original = {f.name: getattr(value, f.name) for f in fields(value)}
        updated = _labelled(original, labels)
        assert isinstance(updated, dict)
        return replace(value, **{key: item for key, item in updated.items() if key in original})
    if isinstance(value, Mapping):
        result = {
            key: item if key in OPAQUE else _labelled(item, labels) for key, item in value.items()
        }
        for identity, label in PAIRS.items():
            selected = value.get(identity)
            names = labels["task" if "task" in identity else "run"]
            if isinstance(selected, int):
                result[label] = names.get(selected, "")
            elif isinstance(selected, (tuple, list)):
                result[label] = tuple(names.get(item, "") for item in selected)
        return result
    if isinstance(value, tuple):
        return tuple(_labelled(item, labels) for item in value)
    if isinstance(value, list):
        return [_labelled(item, labels) for item in value]
    return value
