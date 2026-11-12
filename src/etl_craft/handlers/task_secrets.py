"""Resolve only a script's admitted provider names and inspect literal secret calls."""

import ast
import json
from pathlib import Path

from etl_craft.config.resolve import resolve_named_secret
from etl_craft.core.enums import Handler
from etl_craft.core.errors import EtlCraftError, PermanentError
from etl_craft.core.task_secrets import declared, read
from etl_craft.handlers.registry import TaskContext


def resolve(task: TaskContext) -> dict[str, str]:
    """Keep provider values out of metadata and missing-value error details."""
    label = (
        f"channel {task.task_params['ALERT_CHANNEL']}"
        if task.task_params.get("ALERT_CHANNEL") and task.handler == Handler.EMAIL_ALERT
        else f"{task.pipeline_code}.{task.task_code}"
    )
    result = {}
    for name in declared(task.task_params, label):
        try:
            result[name] = resolve_named_secret(task.config, name)
        except EtlCraftError:
            raise PermanentError(
                f"{label}: secret {name!r} is missing or unavailable from provider "
                f"{task.config.source.type}; set the declared variable in that provider and retry"
            ) from None
    if len(json.dumps(result).encode()) > 1024 * 1024:
        raise PermanentError(
            f"{label}: declared secrets from provider {task.config.source.type} exceed 1 MiB; "
            "reduce the declared values or fetch source data with the source client"
        )
    return result


def problems(task: TaskContext, path: Path) -> None:
    """Validate provider availability without importing or running the script."""
    values = resolve(task)
    label = f"{task.pipeline_code}.{task.task_code}"
    names = declared(task.task_params, label)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "secret"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "task"
        ):
            continue
        if (
            len(node.args) != 1
            or node.keywords
            or not isinstance(node.args[0], ast.Constant)
            or not isinstance(node.args[0].value, str)
        ):
            continue
        read(values, names, label, str(task.config.source.type), node.args[0].value)
