"""The task read the API, UI and CLI share hides team-named sensitive parameter values."""

import json
from dataclasses import replace

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.offsets import TaskInput
from fixtures.metadata import add_pipeline, add_task


def test_task_definitions_hide_sensitive_team_parameters_and_follow_custom_patterns(engine_db):
    with acting_as(SYSTEM_ACTOR), engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        add_task(
            conn,
            pipeline,
            "script",
            handler="PYTHON",
            SCRIPT_FILE="python_scripts/s.py",
            api_token="read-hidden-token",
            ACCOUNT_REF="acct-77",
            INPUT_PARAMS=json.dumps({"db_password": "pw-1", "region": "eu"}),
        )
        add_task(conn, pipeline, "merge", SQL_ACTION="SCD1_MERGE", MERGE_KEY="customer_id")
    ctx = OperationContext(engine_db.engine, engine_db.config, SYSTEM_ACTOR, role=ApiRole.ADMIN)
    script = invoke(ctx, ActionName.TASK, TaskInput(pipeline_code="P", task_code="script"))
    assert script.parameters["api_token"] == "[REDACTED]"
    assert script.parameters["ACCOUNT_REF"] == "acct-77"
    assert json.loads(script.parameters["INPUT_PARAMS"]) == {
        "db_password": "[REDACTED]",
        "region": "eu",
    }
    merge = invoke(ctx, ActionName.TASK, TaskInput(pipeline_code="P", task_code="merge"))
    assert merge.parameters["MERGE_KEY"] == "customer_id" and merge.merge_key == ("customer_id",)
    custom = replace(ctx, config=replace(ctx.config, sensitive_patterns=("*_REF",)))
    script = invoke(custom, ActionName.TASK, TaskInput(pipeline_code="P", task_code="script"))
    assert script.parameters["ACCOUNT_REF"] == "[REDACTED]"
    assert script.parameters["api_token"] == "read-hidden-token"
    from etl_craft.services.catalog.collect import collect_catalog

    catalog = collect_catalog(engine_db.engine, engine_db.config, record_lineage=False)
    shown = next(t.params for t in catalog.tasks.values() if t.params.get("api_token"))
    assert shown["api_token"] == "[REDACTED]"
    assert json.loads(shown["INPUT_PARAMS"])["db_password"] == "[REDACTED]"
