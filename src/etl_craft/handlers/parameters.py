"""Accepted built-in task parameters, shared by validation and execution."""

import importlib
from collections.abc import Mapping

from etl_craft.core.compatibility import input_refusal
from etl_craft.core.enums import Handler, InputKind
from etl_craft.core.errors import MetadataError
from etl_craft.handlers.registry import COMMON_PARAMETERS, HANDLERS


def known_parameters(handler: str) -> frozenset[str] | None:
    """Load only the selected handler; Python scripts own their argument names."""
    if handler == Handler.PYTHON:
        return None
    target = HANDLERS.get(handler) or {
        Handler.EVENT_WAIT.value: "etl_craft.handlers.event_wait:run",
        Handler.RUN_PIPELINE.value: "etl_craft.handlers.run_pipeline:run",
    }.get(handler)
    if target is None:
        return None
    module = target.split(":", 1)[0]
    if module == "etl_craft.handlers.sql":
        module += ".spec"
    return frozenset(getattr(importlib.import_module(module), "PARAMETERS", ()))


def parameter_problems(handler: str, params: Mapping[str, str]) -> list[str]:
    """Refuse unknown inputs to built-in handlers without constraining team scripts."""
    known = known_parameters(handler)
    if known is None:
        return []
    return [
        input_refusal(InputKind.PARAMETER, name)
        for name in sorted(params.keys() - known - COMMON_PARAMETERS)
    ]


def require_task_parameters(handler: str, params: Mapping[str, str]) -> None:
    """Refuse before either a local or remote handler executes."""
    problems = parameter_problems(handler, params)
    if problems:
        raise MetadataError(f"{handler} task parameters: " + "; ".join(problems))
