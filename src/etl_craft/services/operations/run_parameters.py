"""Parse, validate and admit immutable per-run task inputs for every interface."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from sqlalchemy.engine import Connection

from etl_craft.core.definitions import Definition, using
from etl_craft.core.enums import Handler, RunStatus, YesNo
from etl_craft.core.errors import EtlCraftError, UsageError
from etl_craft.core.text import is_secret_name, sha256_hex
from etl_craft.engine import run_overrides, run_scopes, runlog, standing_pauses, transitions
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import current_project_id, resolve_pipeline_id
from etl_craft.engine.repository.tasks import admitted_parameters
from etl_craft.engine.run_definitions import for_admission
from etl_craft.execution.manual import select_tasks
from etl_craft.handlers.python_scripts import parse_input_params
from etl_craft.handlers.sql.spec import FLAGS, read_action, read_flag, read_reject_limit
from etl_craft.handlers.sql.watermarks import read_watermark
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import RunRequest


def parse(values: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Keep string values verbatim, including equals signs; never accept a last-key-wins map."""
    result: dict[str, dict[str, str]] = {}
    if not isinstance(values, (tuple, list)) or any(not isinstance(v, str) for v in values):
        raise UsageError(
            f"params={values!r}: expected a list of TASK.PARAM=VALUE strings; correct params"
        )
    for written in values:
        target, separator, value = written.partition("=")
        task, dot, name = target.partition(".")
        if is_secret_name(name if dot else target):
            raise UsageError(
                f"override {target}=[REDACTED]: expected a data input, not credentials; "
                "keep secrets as configured variable references"
            )
        if not separator or not dot or not task or not name or "." in name:
            raise UsageError(f"override {written!r}: expected TASK.PARAM=VALUE; correct --param")
        if name in result.setdefault(task, {}):
            raise UsageError(
                f"override {target}={value!r}: duplicate key; expected one value; "
                f"remove the repeated --param"
            )
        result[task][name] = value
    return result


def validate(definition: Definition, values: dict[str, dict[str, str]], pipeline_id: int) -> None:
    """Only existing data inputs may change; execution, scripts, secrets and targets stay pinned."""
    tasks = {
        str(t["task_code"]): t
        for t in definition.rows["CFG_TASKS"]
        if t["active_flag"] == YesNo.YES and t["pipeline_id"] == pipeline_id
    }
    for code, changes in values.items():
        task = tasks.get(code)
        if task is None:
            raise UsageError(
                f"override task {code!r}: unknown; expected an active task in "
                f"this pipeline; correct --param"
            )
        task_id = task["task_id"]
        assert isinstance(task_id, int)
        params = admitted_parameters(definition, task_id)
        allowed = (
            {"INPUT_PARAMS"}
            if task["handler"] == Handler.PYTHON
            else {"WATERMARK_START", "REJECT_LIMIT", "ALLOW_EMPTY"}
            if task["handler"] == Handler.SQL
            else set()
        )
        for name, value in changes.items():
            if name not in params or name not in allowed:
                raise UsageError(
                    f"override {code}.{name}={value!r}: expected an existing "
                    f"data-input parameter in {sorted(allowed)}; correct --param; "
                    f"code, targets, secrets and controls cannot be overridden"
                )
            try:
                if name == "INPUT_PARAMS":
                    parse_input_params(value)
                elif name in FLAGS:
                    read_flag({**params, **changes}, name, read_action(params), FLAGS[name])
                elif name == "REJECT_LIMIT":
                    read_reject_limit({**params, **changes}, read_action(params))
                elif name == "WATERMARK_START":
                    read_watermark({**params, **changes})
            except EtlCraftError as error:
                raise UsageError(
                    f"override {code}.{name}={value!r}: {error}; correct --param"
                ) from error


def admit(ctx: OperationContext, request: RunRequest) -> tuple[RunRequest, int, bool]:
    """Serialize project-key admission and commit the run and its input record together."""
    values = parse(request.params)
    if (
        not isinstance(request.request_key, str)
        or not request.request_key.strip()
        or len(request.request_key) > 128
    ):
        raise UsageError(
            f"run overrides: request_key={request.request_key!r}; "
            "expected a nonempty key of at most 128 characters; supply --request-key KEY"
        )
    if (
        request.run_id is not None
        or request.run_key is not None
        or request.backfill
        or request.skip
        or request.rerun
        or request.force
        or (request.task_code and not request.standalone)
    ):
        raise UsageError(
            "run overrides: expected a new pipeline/init/standalone run; omit "
            "existing run selectors, backfill, skip, force and rerun"
        )
    digest = _digest(request, values)
    with ctx.engine.begin() as conn:
        pipeline_id = resolve_pipeline_id(conn, request.pipeline_code)
        project = current_project_id()
        conn.execute(statement(conn, "run_overrides_lock"), {"project_id": project}).one()
        existing = conn.execute(
            statement(conn, "run_overrides_key"),
            {"project_id": project, "request_key": request.request_key},
        ).one_or_none()
        if existing is not None:
            if existing.request_digest != digest or existing.pipeline_id != pipeline_id:
                raise UsageError(
                    f"request_key={request.request_key!r}: payload differs; "
                    f"expected its recorded canonical inputs; reuse them or "
                    f"choose a new key"
                )
            return request, int(existing.run_id), True
        standing_pauses.lock(conn, pipeline_id)
        with _base(conn, pipeline_id) as base:
            validate(base, values, pipeline_id)
            key = f"override:{request.request_key}"
            if request.standalone:
                scope = select_tasks(
                    conn,
                    pipeline_id,
                    request.task_code or "",
                    with_downstream=request.with_downstream,
                    ignore_dependencies=request.ignore_dependencies,
                )
                run_id = run_scopes.create_manual_run(
                    conn,
                    pipeline_id,
                    ctx.actor,
                    scope,
                    key,
                    request.run_date or runlog.today(ctx.config.timezone),
                )
            else:
                run_id = transitions.create_run(
                    conn,
                    pipeline_id,
                    ctx.actor,
                    run_key=key,
                    run_date=request.run_date or runlog.today(ctx.config.timezone),
                    status=RunStatus.QUEUED,
                )
            run_overrides.store(conn, run_id, project, request.request_key, digest, values)
        from etl_craft.engine.run_definitions import read

        actual, _ = read(conn, run_id)
        validate(actual, values, pipeline_id)
    return replace(request, params=(), request_key=None, run_id=run_id), run_id, False


def copy_for_restart(conn: Connection, source: int, pipeline_id: int) -> dict[str, dict[str, str]]:
    """Refuse incompatible new definitions before a replacement run is written."""
    values = run_overrides.recorded(conn, source)
    if values:
        with _base(conn, pipeline_id) as base:
            validate(base, values, pipeline_id)
    return values


def _digest(request: RunRequest, values: dict[str, dict[str, str]]) -> str:
    """Canonicalize submission identity independently of parameter ordering."""
    return sha256_hex(
        json.dumps(
            {
                "pipeline": request.pipeline_code,
                "task": request.task_code,
                "date": str(request.run_date),
                "standalone": request.standalone,
                "downstream": request.with_downstream,
                "ignore_dependencies": request.ignore_dependencies,
                "values": values,
            },
            sort_keys=True,
        ).encode()
    )


@contextmanager
def _base(conn: Connection, pipeline_id: int) -> Iterator[Definition]:
    with for_admission(conn, pipeline_id) as base:
        if base is None:
            base = Definition.read(
                conn.execute(
                    statement(conn, "run_overrides_base"), {"pipeline_id": pipeline_id}
                ).scalar_one()
            )
        with using(base):
            yield base
