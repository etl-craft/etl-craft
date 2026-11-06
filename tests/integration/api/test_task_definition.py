"""A task's definition and parsed merge columns, as the task page reads them."""

import pytest

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.metadata import add_pipeline, add_task

OWNER = Actor("owner", ActorKind.USER)


@pytest.fixture
def site(metadata_project):
    from etl_craft.engine.migrations import mark_packaged_migrations_applied

    p = metadata_project
    with p.engine.begin() as conn:
        mark_packaged_migrations_applied(conn)
    ctx = OperationContext(p.engine, p.config, OWNER, role=ApiRole.ADMIN)
    with acting_as(OWNER), p.engine.begin() as conn:
        pipeline = add_pipeline(conn, "SALES")
        add_task(
            conn,
            pipeline,
            "CUSTOMERS",
            "SQL",
            SQL_ACTION="SCD2_MERGE",
            TARGET_OBJECT="dm.customers",
            SELECT_QUERY="SELECT customer_id, region, name FROM ods.customers",
            MERGE_KEY="customer_id|region",
            MERGE_COMPARE_COLUMNS="name",
        )
        add_task(conn, pipeline, "NOTIFY", "EMAIL_ALERT")
    return ctx, None


def test_task_read_returns_the_definition_and_parsed_merge_columns(site):
    ctx, _ = site
    task = act(ctx, ActionName.TASK, pipeline_code="SALES", task_code="CUSTOMERS")
    assert (task.handler, task.merge_key, task.merge_columns) == (
        "SQL",
        ("customer_id", "region"),
        ("name",),
    )
    assert task.parameters["SQL_ACTION"] == "SCD2_MERGE"
    other = act(ctx, ActionName.TASK, pipeline_code="SALES", task_code="NOTIFY")
    assert (other.merge_key, other.merge_columns) == ((), ())
