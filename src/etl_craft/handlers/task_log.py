"""The opening and closing blocks of every task log, written by both task processes.

The opening block says what runs, where and with which inputs; the closing block says how it
ended. Together with each handler's step lines they let someone debug a failure from the log
alone. Values pass through the log handler's masking; parameters a team named as sensitive are
hidden here as they are in the API.
"""

from __future__ import annotations

import json
import logging
import socket
import time

from etl_craft.config.targets import active_warehouse, parse_warehouse_url
from etl_craft.core.errors import EtlCraftError
from etl_craft.core.failures import Failure
from etl_craft.core.redaction import public_parameters
from etl_craft.handlers.parameters import package_parameters
from etl_craft.handlers.registry import HandlerResult, TaskContext

logger = logging.getLogger(__name__)
# A task process runs one task: the monotonic time its opening block was logged.
_started: float | None = None


def opening(context: TaskContext) -> None:
    """Log the task's context block and start timing the task."""
    global _started
    attempt = "" if context.attempt_id is None else f", attempt {context.attempt_id}"
    logger.info(
        "task %s.%s: try %d%s, %s handler, on host %s",
        context.pipeline_code,
        context.task_code,
        context.attempt,
        attempt,
        context.handler,
        socket.gethostname(),
    )
    modes = [
        name
        for name, on in (
            ("full refresh", context.full_refresh),
            ("backfill", context.backfill),
            ("forced", context.force),
            ("rerun", context.rerun),
        )
        if on
    ]
    logger.info(
        "pipeline run %d (task run %d) as of %s, refresh type %s%s",
        context.pipeline_run_id,
        context.task_run_id,
        context.run_date.isoformat(),
        context.refresh_type,
        f" ({', '.join(modes)})" if modes else "",
    )
    if context.config.warehouse is not None:
        url = parse_warehouse_url(context.config.warehouse.jdbc_url)
        logger.info(
            "warehouse: %s%s",
            active_warehouse(context.config).display_name,
            f" at {url.host}" if url.host else "",
        )
    shown = public_parameters(
        context.task_params, context.config.sensitive_patterns, package_parameters()
    )
    for name in sorted(shown):
        value = _bound_keys(shown[name]) if name.upper() == "INPUT_PARAMS" else shown[name]
        logger.info("parameter %s = %s", name, value)
    _started = time.monotonic()


def _bound_keys(value: str) -> str:
    """Name ``INPUT_PARAMS``' keys only: its values are bound into SQL and never logged."""
    try:
        document = json.loads(value)
    except ValueError:
        document = None
    keys = ", ".join(str(key) for key in document) if isinstance(document, dict) else ""
    return f"keys {keys} (values not shown)" if keys else "(values not shown)"


def succeeded(result: HandlerResult) -> None:
    """Log the closing block of a task that ended SUCCESS."""
    logger.info(
        "task succeeded%s: source %s, target %s, inserted %s, updated %s, deleted %s, "
        "rejected %s, duplicates %s",
        _elapsed(),
        result.source_count,
        result.target_count,
        result.insert_count,
        result.update_count,
        result.delete_count,
        result.reject_count,
        result.duplicate_count,
    )


def failed(error: BaseException, failure: Failure) -> None:
    """Log the closing block of a failed task: its class, its cause and the message's remedy."""
    code = f" {failure.code}" if failure.code else ""
    logger.error(
        "task failed%s: %s failure (%s%s): %s",
        _elapsed(" after"),
        failure.kind,
        failure.source,
        code,
        error if isinstance(error, EtlCraftError) else f"{type(error).__name__}: {error}",
    )


def _elapsed(word: str = " in") -> str:
    """Say how long the task ran since its opening block, once; nothing when it never opened."""
    global _started
    if _started is None:
        return ""
    elapsed, _started = time.monotonic() - _started, None
    return f"{word} {elapsed:.1f}s"
