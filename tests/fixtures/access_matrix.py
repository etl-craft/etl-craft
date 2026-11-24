"""Record every action's authorization decision for each kind of principal.

A small estate (projects sales and hr, pipelines P1 tagged t1 and P2 in sales, each with a run
and an attempt; sales gives the viewer and operator audiences CAN_VIEW and CAN_RUN, as the default
project does) and eleven principals, each holding one kind of access. Every action is asked
for through the real ``admitted`` check, naming P1 or P2 where the request names a pipeline.
The outcome table is compared with ``tests/fixtures/access_matrix.tsv``.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import text

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole, ControlAction
from etl_craft.core.errors import EtlCraftError, PermissionDeniedError, ResourceNotFoundError
from etl_craft.engine import transitions
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import ACTIONS, admitted, invoke
from etl_craft.services.operations.requests import ControlRequest
from fixtures.actions import act
from fixtures.actions import build as build_request
from fixtures.metadata import add_pipeline, add_task, start_run

MATRIX = Path(__file__).parent / "access_matrix.tsv"
OWNER = Actor("owner", ActorKind.USER)
PIPELINES = ("P1", "P2")


@dataclass(frozen=True)
class Principal:
    """An account, its deployment role and the one grant it holds, if any."""

    name: str
    role: ApiRole
    grant: dict[str, str] | None = None


PRINCIPALS = (
    Principal("admin", ApiRole.ADMIN),
    Principal("developer", ApiRole.DEVELOPER),
    Principal("operator", ApiRole.OPERATOR),
    Principal("viewer", ApiRole.VIEWER),
    Principal("view_p1", ApiRole.VIEWER, {"role": "CAN_VIEW", "pipeline": "P1"}),
    Principal("upload_t1", ApiRole.VIEWER, {"role": "CAN_UPLOAD", "tag": "t1"}),
    Principal("run_p1", ApiRole.VIEWER, {"role": "CAN_RUN", "pipeline": "P1"}),
    Principal("manage_sales", ApiRole.VIEWER, {"role": "CAN_MANAGE"}),
    Principal("runner_role", ApiRole.VIEWER, {"role": "runner"}),
    Principal("rehash_action", ApiRole.VIEWER, {"action": "rehash"}),
    Principal("agent", ApiRole.AGENT),
)


@dataclass
class Estate:
    admin: OperationContext
    ids: dict[str, dict[str, int]]


def build_estate(engine_db) -> Estate:  # type: ignore[no-untyped-def]
    """Create the projects, pipelines, runs, attempts, accounts and grants."""
    admin = OperationContext(
        engine_db.engine, engine_db.config, OWNER, role=ApiRole.ADMIN, project="sales"
    )
    for code, environment in (("sales", "DEV"), ("hr", "PROD")):
        act(admin, ActionName.PROJECT_ADD, project=code, environment_type=environment,
            reason="matrix")  # fmt: skip
    with admin.engine.connect() as conn:
        sales = conn.execute(
            text("SELECT PROJECT_ID AS id FROM CFG_PROJECTS WHERE PROJECT_CODE='sales'")
        ).scalar_one()
    ids: dict[str, dict[str, int]] = {}
    with acting_as(OWNER), admin.engine.begin() as conn:
        for code in PIPELINES:
            pipeline = add_pipeline(conn, code, project_id=sales)
            if code == "P1":
                conn.execute(
                    text("UPDATE CFG_PIPELINES SET PIPELINE_PARAMETERS=:p WHERE PIPELINE_ID=:i"),
                    {"p": json.dumps({"TAGS": ["t1"]}), "i": pipeline},
                )
            task = add_task(conn, pipeline, "T1")
            run = start_run(conn, pipeline)
            summary = transitions.find_or_create_task_run(conn, task, run).task_run_id
            attempt = transitions.queue_attempt(conn, summary, OWNER)
            ids[code] = {"run_id": run, "task_run_id": summary, "attempt_id": attempt}
    # The audience defaults every project in this estate starts from, as the default project does.
    for audience, role in (("viewer", "CAN_VIEW"), ("operator", "CAN_RUN")):
        act(admin, ActionName.ACCESS_GRANT, audience=audience, role=role, project="sales",
            reason="matrix")  # fmt: skip
    act(admin, ActionName.ROLE_CREATE, name="runner", actions=("run", "control", "logs"))
    for principal in PRINCIPALS:
        if principal.role == ApiRole.AGENT:
            continue
        act(admin, ActionName.ACCOUNT_ADD, name=principal.name, role=principal.role,
            oidc_subject=f"{principal.name}-sub")  # fmt: skip
        if principal.grant is not None:
            act(admin, ActionName.ACCESS_GRANT, account=principal.name, project="sales",
                reason="matrix", **principal.grant)  # fmt: skip
    return Estate(admin, ids)


SCOPE: dict[str, object] = {"task_code": "T1", "project": "sales"}
WHOLE = frozenset({ActionName.ACCESS_GRANT, ActionName.ACCESS_REVOKE})
"""Actions that authorize inside the operation too; they run whole, as a dry run."""


def request_for(name: ActionName, pipeline: str, ids: dict[str, dict[str, int]]) -> object:
    """Build the action's request naming ``pipeline`` and its run, task run and attempt."""
    request_type = ACTIONS[name].request
    if not dataclasses.is_dataclass(request_type):
        return request_type()
    if name in WHOLE:
        return request_type(
            project="sales", account="viewer", role="CAN_VIEW", pipeline=pipeline,
            reason="matrix", dry_run=True,
        )  # fmt: skip
    names = {f.name for f in dataclasses.fields(request_type)}
    values = {
        key: value
        for key, value in {"pipeline_code": pipeline, **ids[pipeline], **SCOPE}.items()
        if key in names
    }
    if name == ActionName.CAPABILITIES:
        values.pop("attempt_id", None)  # the run-control answer takes no attempt; logs ask with it
    if name == ActionName.CONTROL_BULK:
        values["requests"] = (
            ControlRequest(
                pipeline_code=pipeline,
                action=ControlAction.STOP,
                run_id=ids[pipeline]["run_id"],
                request_key=f"matrix-{pipeline}",
            ),
        )
    return dataclasses.replace(build_request(request_type), **values)


def names_pipeline(name: ActionName) -> bool:
    request_type = ACTIONS[name].request
    return dataclasses.is_dataclass(request_type) and any(
        f.name in ("pipeline_code", "run_id", "attempt_id", "task_run_id")
        for f in dataclasses.fields(request_type)
    )


def decide(ctx: OperationContext, name: ActionName, request: object) -> str:
    """Return allow, deny, hidden, or the class of any other refusal."""
    try:
        if name in WHOLE:
            invoke(ctx, name, request)
            return "allow"
        with admitted(ctx, name, request):
            return "allow"
    except PermissionDeniedError:
        return "deny"
    except ResourceNotFoundError:
        return "hidden"
    except EtlCraftError as error:
        return f"refused:{type(error).__name__}"


def render(estate: Estate) -> str:
    """One line per action, principal and target pipeline."""
    lines = ["action\tprincipal\tpipeline\toutcome"]
    for name in sorted(ACTIONS, key=str):
        targets = PIPELINES if names_pipeline(name) else ("-",)
        for principal in PRINCIPALS:
            kind = ActorKind.SERVICE if principal.role == ApiRole.AGENT else ActorKind.USER
            ctx = replace(estate.admin, actor=Actor(principal.name, kind), role=principal.role)
            for target in targets:
                request = request_for(name, "P1" if target == "-" else target, estate.ids)
                outcome = decide(ctx, name, request)
                lines.append(f"{name}\t{principal.name}\t{target}\t{outcome}")
    return "\n".join(lines) + "\n"
