"""Atomically replace each item batch before a downstream managed SQL task."""

from etl_craft.scripting import Offset, ScriptResult, ScriptTask


def run(task: ScriptTask) -> ScriptResult:
    """Replace rows in the declared landing target using its CFG_COLUMNS contract."""

    def load(key: str) -> ScriptResult:
        position = task.offset.value.get(key, 0) if task.offset else 0
        rows = ({"delivery_key": key, "position": position},)
        return ScriptResult(
            task.replace_landing(iter(rows), item_key=key), Offset.partitions({key: position + 1})
        )

    return task.fan_out(task.input_params["keys"], load, max_items=1000, max_parallel=16, retries=1)
