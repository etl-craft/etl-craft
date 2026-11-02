"""Fresh-process protection mutations for real process-loss tests."""

import os

from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.dialects.engine import build_engine
from etl_craft.services.operations import OperationContext
from fixtures.actions import act


def mutate(config, kind, target, point, context=None):
    os.environ["ETL_CRAFT_FAULT"] = point + ":kill"
    engine = build_engine(config)
    ctx = OperationContext(engine, config, Actor("alice", ActorKind.USER), role=ApiRole.ADMIN)
    base = {"pipeline_code": "P", "task_code": "load", "key": {"id": 1}, "reason": "correct"}
    if kind == "edit":
        act(ctx, ActionName.DATA_EDIT, **base, values={"name": "After"})
    elif kind == "unlock":
        act(ctx, ActionName.DATA_UNLOCK, **base, columns=("name",))
    elif kind == "rehash":
        act(ctx, ActionName.REHASH, target=target)
    elif kind == "erasure":
        from etl_craft.core.actor import acting_as
        from etl_craft.core.erasure import ErasureEntry
        from etl_craft.handlers.erasure import apply_entries

        with acting_as(ctx.actor):
            apply_entries(engine, config, (ErasureEntry(target, "id", "1", "a" * 64),))
    elif kind in {"hard_delete", "upload", "reload"}:
        from contextlib import nullcontext

        from etl_craft.core.actor import acting_as
        from etl_craft.engine.resource_locks import attempt_scope
        from etl_craft.handlers import sql

        scope = (
            attempt_scope(context.attempt_id, context.owner)
            if context.attempt_id is not None
            else nullcontext()
        )
        with acting_as(ctx.actor), scope:
            sql.run(context, engine)
