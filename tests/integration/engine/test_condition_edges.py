"""Task run conditions derive stable edges and refuse cycles across scopes."""

from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.errors import ConditionError
from etl_craft.engine.condition_edges import derive_edges
from fixtures.metadata import add_pipeline, add_task


def write_condition(conn, task, rule):
    conn.execute(
        text("UPDATE CFG_TASKS SET RUN_CONDITION=:rule WHERE TASK_ID=:task"),
        {"rule": rule, "task": task},
    )


@pytest.mark.parametrize("scope", ["pipeline", "project", "cross_project"])
def test_condition_cycle_names_all_tasks(engine_db, scope):
    with engine_db.engine.begin() as conn:
        first = add_pipeline(conn, "FIRST")
        second = first
        project_id = 1
        if scope == "cross_project":
            project_id = conn.execute(
                text(
                    "INSERT INTO CFG_PROJECTS (PROJECT_CODE,PROJECT_NAME,DEFAULT_POOL) "
                    "VALUES ('second','second','default') RETURNING PROJECT_ID AS project_id"
                )
            ).scalar_one()
        if scope != "pipeline":
            second = add_pipeline(conn, "SECOND", project_id=project_id)
        load = add_task(conn, first, "load")
        report = add_task(conn, second, "report")
        if scope == "cross_project":
            write_condition(conn, report, "default.FIRST.load.SUCCESS")
            derive_edges(conn, project_id)
            write_condition(conn, load, "second.SECOND.report.SUCCESS")
        elif scope == "project":
            write_condition(conn, load, "SECOND.report.SUCCESS")
            write_condition(conn, report, "FIRST.load.SUCCESS")
        else:
            write_condition(conn, load, "report.SUCCESS")
            write_condition(conn, report, "load.SUCCESS")
        with pytest.raises(ConditionError, match="cycle") as error:
            derive_edges(conn, 1)
        assert "FIRST.load" in str(error.value)
        assert ("FIRST.report" if scope == "pipeline" else "SECOND.report") in str(error.value)


def test_reinstated_condition_keeps_its_edge_identity(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "FLOW")
        add_task(conn, pipeline, "extract")
        load = add_task(conn, pipeline, "load")
        write_condition(conn, load, "extract.SUCCESS")
        assert derive_edges(conn, 1) == 1
        query = text(
            "SELECT TASK_DEPENDENCY_ID AS edge, ACTIVE_FLAG AS active FROM CFG_TASK_DEPENDENCY"
        )
        original = conn.execute(query).one()
        write_condition(conn, load, None)
        assert derive_edges(conn, 1) == 1
        assert conn.execute(query).one().active == "N"
        write_condition(conn, load, "extract.HAS_DATA")
        assert derive_edges(conn, 1) == 1
        restored = conn.execute(query).one()
        assert (restored.edge, restored.active) == (original.edge, "Y")


def test_layered_conditions_accept_two_thousand_tasks(engine_db):
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "LAYERED")
        conn.execute(
            text(
                "INSERT INTO CFG_TASKS (PIPELINE_ID, TASK_CODE, TASK_TYPE, HANDLER, RUN_CONDITION) "
                "VALUES (:pipeline,:task,'ETL','SQL',:rule)"
            ),
            [
                {
                    "pipeline": pipeline,
                    "task": f"t{i}",
                    "rule": f"t{i - 10}.SUCCESS" if i >= 10 else None,
                }
                for i in range(2000)
            ],
        )
        assert derive_edges(conn, 1) == 1990
        assert derive_edges(conn, 1) == 0


def test_validate_names_the_config_file_line_for_a_bad_condition(engine_db, tmp_path):
    from etl_craft.services.validate import validate

    config = replace(engine_db.config, config_path=tmp_path / "craft-connector.yml")
    folder = config.project_dir / "config"
    folder.mkdir()
    path = folder / "tasks.csv"
    path.write_text(
        "PIPELINE_CODE,TASK_CODE,TASK_TYPE,HANDLER,RUN_CONDITION\nPIPE,build,ETL,SQL,load.SUCESS\n"
    )
    with engine_db.engine.begin() as conn:
        pipeline = add_pipeline(conn, "PIPE")
        add_task(conn, pipeline, "load")
        build = add_task(conn, pipeline, "build")
        write_condition(conn, build, "load.SUCESS")
    report = validate(engine_db.engine, config, "PIPE")
    assert report.failed
    finding = next(item for item in report.findings if str(path) in item.where)
    assert finding.where == f"{path} line 2"
    for part in ("PIPE.build", "column RUN_CONDITION", "position", "SUCESS", "SUCCESS", "deploy"):
        assert part in finding.message
