"""Derivation and refusals for pipeline start conditions."""

import pytest
from sqlalchemy import text

from etl_craft.core.errors import ConditionError
from etl_craft.engine.condition_edges import derive_edges
from fixtures.metadata import add_pipeline, add_pipeline_dependency, insert


def set_condition(conn, pipeline, condition):
    conn.execute(
        text("UPDATE CFG_PIPELINES SET START_CONDITION=:condition WHERE PIPELINE_ID=:pipeline"),
        {"condition": condition, "pipeline": pipeline},
    )


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("DOWN.SUCCESS", "names this pipeline"),
        ("default.DOWN.SUCCESS", "names this pipeline"),
        ("defaul.LOAD.SUCCESS", "did you mean default"),
        ("LODA.SUCCESS", "did you mean LOAD"),
        ("RETIRED.SUCCESS", "expected an active project and pipeline"),
    ],
)
def test_pipeline_start_condition_refuses_bad_names(engine_db, rule, expected):
    with engine_db.engine.begin() as conn:
        consumer = add_pipeline(conn, "DOWN")
        add_pipeline(conn, "LOAD")
        retired = add_pipeline(conn, "RETIRED")
        conn.execute(
            text("UPDATE CFG_PIPELINES SET ACTIVE_FLAG='N' WHERE PIPELINE_ID=:id"), {"id": retired}
        )
        set_condition(conn, consumer, rule)
        with pytest.raises(ConditionError) as error:
            derive_edges(conn, 1)
    message = str(error.value)
    for part in ("DOWN START_CONDITION position 1", rule.rsplit(".", 1)[0], expected):
        assert part in message


@pytest.mark.parametrize("cross_project", [False, True])
def test_pipeline_start_condition_names_a_cycle(engine_db, cross_project):
    with engine_db.engine.begin() as conn:
        project = (
            insert(
                conn,
                "INSERT INTO CFG_PROJECTS (PROJECT_CODE, PROJECT_NAME, DEFAULT_POOL) "
                "VALUES ('other', 'other', 'default')",
                "PROJECT_ID",
            )
            if cross_project
            else 1
        )
        first = add_pipeline(conn, "FIRST")
        second = add_pipeline(conn, "SECOND", project_id=project)
        add_pipeline_dependency(conn, first, second)
        set_condition(conn, second, "default.FIRST.SUCCESS" if cross_project else "FIRST.SUCCESS")
        with pytest.raises(ConditionError) as error:
            derive_edges(conn, project)
    second_name = "other.SECOND" if cross_project else "default.SECOND"
    assert f"default.FIRST -> {second_name} -> default.FIRST" in str(error.value)
    assert "remove one of these names" in str(error.value)


def test_pipeline_edge_identity_survives_removal_and_reactivation(engine_db):
    with engine_db.engine.begin() as conn:
        first = add_pipeline(conn, "FIRST")
        second = add_pipeline(conn, "SECOND")
        edge = add_pipeline_dependency(conn, first, second)
        set_condition(conn, first, None)
        assert derive_edges(conn, 1) == 1
        assert (
            conn.execute(
                text(
                    "SELECT ACTIVE_FLAG FROM CFG_PIPELINE_DEPENDENCY "
                    "WHERE PIPELINE_DEPENDENCY_ID=:id"
                ),
                {"id": edge},
            ).scalar_one()
            == "N"
        )
        assert add_pipeline_dependency(conn, first, second, "ALWAYS") == edge


def test_pipeline_start_conditions_accept_a_deep_chain(engine_db):
    with engine_db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO CFG_PIPELINES "
                "(PIPELINE_CODE, PIPELINE_NAME, REFRESH_TYPE, START_CONDITION) "
                "VALUES (:code, :code, 'FULL', :rule)"
            ),
            [
                {"code": f"P{i:04}", "rule": f"P{i - 1:04}.SUCCESS" if i else None}
                for i in range(2000)
            ],
        )
        assert derive_edges(conn, 1) == 1999
        assert derive_edges(conn, 1) == 0


def test_a_start_edge_and_a_cross_pipeline_task_edge_do_not_form_a_start_cycle(engine_db):
    from fixtures.metadata import add_dependency, add_task

    with engine_db.engine.begin() as conn:
        first = add_pipeline(conn, "FIRST")
        second = add_pipeline(conn, "SECOND")
        upstream = add_task(conn, first, "upstream")
        consumer = add_task(conn, second, "consumer")
        add_pipeline_dependency(conn, first, second)
        add_dependency(conn, second, consumer, upstream, upstream_pipeline=first)
        assert derive_edges(conn, 1) == 0
