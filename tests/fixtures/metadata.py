"""Rows for tests: pipelines, tasks, dependencies, and finished runs of them."""

from sqlalchemy import inspect, text

from etl_craft.core.counts import Counts
from etl_craft.engine import runlog, transitions
from etl_craft.engine.condition_edges import derive_edges
from etl_craft.engine.project_scope import configured_project
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import selected_project


def insert(conn, sql, id_column, **params):
    return conn.execute(text(f"{sql} RETURNING {id_column}"), params).scalar_one()


def pipeline_project_id(conn, pipeline_id):
    """Resolve the project owned by the fixture's exact pipeline."""
    return int(
        conn.execute(
            statement(conn, "pipeline_project_id"), {"pipeline_id": pipeline_id}
        ).scalar_one()
    )


def add_pipeline(conn, code, *, refresh_type="FULL", sla_in_hours=None, project_id=None):
    return insert(
        conn,
        "INSERT INTO CFG_PIPELINES (PIPELINE_CODE, PIPELINE_NAME, REFRESH_TYPE, SLA_IN_HOURS"
        + (", PROJECT_ID" if project_id is not None else "")
        + ") VALUES (:code, :code, :refresh, :sla"
        + (", :project" if project_id is not None else "")
        + ")",
        "PIPELINE_ID",
        code=code,
        refresh=refresh_type,
        sla=sla_in_hours,
        **({"project": project_id} if project_id is not None else {}),
    )


def add_task(conn, pipeline_id, code, handler="SQL", **params):
    task_id = insert(
        conn,
        "INSERT INTO CFG_TASKS (TASK_CODE, TASK_TYPE, PIPELINE_ID, HANDLER) "
        "VALUES (:code, 'ETL', :pipeline, :handler)",
        "TASK_ID",
        code=code,
        pipeline=pipeline_id,
        handler=handler,
    )
    params = dict(params)
    if handler == "PYTHON":
        params.setdefault("SCRIPT_KIND", "INGESTION")
    target = params.get("TARGET_OBJECT")
    task_name = "cfg_tasks" if conn.dialect.name == "postgresql" else "CFG_TASKS"
    if target is not None and any(
        column["name"].upper() == "TARGET_TABLE_ID"
        for column in inspect(conn).get_columns(task_name)
    ):
        set_task_target(conn, task_id, params.pop("TARGET_OBJECT"))
    for name, value in params.items():
        conn.execute(
            text(
                "INSERT INTO CFG_TASK_PARAMETERS (TASK_ID, PARAMETER_NAME, PARAMETER_VALUE) "
                "VALUES (:task, :name, :value)"
            ),
            {"task": task_id, "name": name, "value": str(value)},
        )
    return task_id


def add_dependency(
    conn, pipeline_id, task_id, depends_on, kind="SUCCESS", *, upstream_pipeline=None
):
    project_id = pipeline_project_id(conn, pipeline_id)
    upstream = conn.execute(
        text(
            "SELECT t.TASK_CODE AS task_code, p.PIPELINE_ID AS pipeline_id, "
            "p.PIPELINE_CODE AS pipeline_code, p.PROJECT_ID AS project_id, "
            "j.PROJECT_CODE AS project_code FROM CFG_TASKS t "
            "JOIN CFG_PIPELINES p ON p.PIPELINE_ID=t.PIPELINE_ID "
            "JOIN CFG_PROJECTS j ON j.PROJECT_ID=p.PROJECT_ID WHERE t.TASK_ID=:task"
        ),
        {"task": depends_on},
    ).one()
    fact = {"SUCCESS": "SUCCESS", "FAILURE": "FAILED", "ALWAYS": "FINISHED", "HAS_DATA": "HAS_DATA"}
    parts = [upstream.task_code, fact[kind]]
    if (upstream_pipeline or upstream.pipeline_id) != pipeline_id:
        parts.insert(0, upstream.pipeline_code)
    if upstream.project_id != project_id:
        parts.insert(0, upstream.project_code)
    existing = conn.execute(
        text("SELECT RUN_CONDITION FROM CFG_TASKS WHERE TASK_ID=:task"), {"task": task_id}
    ).scalar_one()
    reference = ".".join(parts)
    condition = f"{existing} AND {reference}" if existing else reference
    conn.execute(
        text("UPDATE CFG_TASKS SET RUN_CONDITION=:condition WHERE TASK_ID=:task"),
        {"condition": condition, "task": task_id},
    )
    derive_edges(conn, project_id)
    return conn.execute(
        text(
            "SELECT TASK_DEPENDENCY_ID FROM CFG_TASK_DEPENDENCY "
            "WHERE TASK_ID=:task AND DEPENDS_ON_TASK_ID=:upstream"
        ),
        {"task": task_id, "upstream": depends_on},
    ).scalar_one()


def add_pipeline_dependency(conn, pipeline_id, depends_on, kind="SUCCESS"):
    return insert(
        conn,
        "INSERT INTO CFG_PIPELINE_DEPENDENCY (PIPELINE_ID, DEPENDS_ON_PIPELINE_ID, "
        "DEPENDENCY_TYPE) VALUES (:p, :d, :k)",
        "PIPELINE_DEPENDENCY_ID",
        p=pipeline_id,
        d=depends_on,
        k=kind,
    )


def start_run(conn, pipeline_id, *, run_date=None, backfill=False):
    """Reuse the active run for a test scene, creating it when none exists."""
    existing = runlog.fetch_active_pipeline_run_id(conn, pipeline_id)
    if existing is not None:
        return existing
    with selected_project(pipeline_project_id(conn, pipeline_id)):
        created = transitions.create_active_run(
            conn, pipeline_id, run_date=run_date, backfill=backfill
        )
    if created is None:
        # Another session created the run between the read and the insert.
        created = runlog.fetch_active_pipeline_run_id(conn, pipeline_id)
    assert created is not None
    return created


def finish_run(conn, pipeline_run_id, status="SUCCESS"):
    transitions.finalize_pipeline_run(conn, pipeline_run_id, status)


def task_run(
    conn, task_id, pipeline_run_id, status="SUCCESS", target_count=None, rows_written=None
):
    """Bind ``task_id`` under the run and end it with ``status``; return its row id."""
    binding = transitions.find_or_create_task_run(conn, task_id, pipeline_run_id)
    if status != "IN-PROGRESS":
        transitions.finish_task_run(
            conn,
            binding.task_run_id,
            status=status,
            counts=Counts(target_count=target_count, rows_written=rows_written),
        )
    return binding.task_run_id


def upstream_run(conn, pipeline_id, task_statuses, status="SUCCESS"):
    """A finished run of ``pipeline_id`` with its tasks ended as given; return the run and rows."""
    run_id = start_run(conn, pipeline_id)
    rows = {
        task_id: task_run(conn, task_id, run_id, *spec) for task_id, spec in task_statuses.items()
    }
    if status != "IN-PROGRESS":
        finish_run(conn, run_id, status)
    return run_id, rows


def add_table(conn, table):
    """Declare a column under one scoped table contract."""
    from etl_craft.engine.repository.normalization import object_identity

    catalog, schema, name = object_identity(table, None, None)
    params = {"catalog": catalog, "schema": schema, "table": name}
    table_id = conn.execute(
        text(
            "SELECT TABLE_ID AS table_id FROM CFG_TABLES WHERE SCHEMA_NAME=:schema "
            "AND TABLE_NAME=:table AND (CATALOG_NAME=:catalog OR "
            "(CATALOG_NAME IS NULL AND :catalog IS NULL))"
        ),
        params,
    ).scalar_one_or_none()
    if table_id is None:
        table_id = conn.execute(
            text(
                "INSERT INTO CFG_TABLES (CATALOG_NAME, SCHEMA_NAME, TABLE_NAME) "
                "VALUES (:catalog, :schema, :table) RETURNING TABLE_ID AS table_id"
            ),
            params,
        ).scalar_one()
    return table_id


def add_source_column(conn, table, column, data_type, position):
    """Declare a column under one scoped table contract."""
    table_id = add_table(conn, table)
    return conn.execute(
        text(
            "INSERT INTO CFG_COLUMNS (TABLE_ID, COLUMN_NAME, DATA_TYPE, COLUMN_POSITION) "
            "VALUES (:table_id, :column, :type, :position) RETURNING COLUMN_ID AS column_id"
        ),
        {"table_id": table_id, "column": column, "type": data_type, "position": position},
    ).scalar_one()


def set_task_target(conn, task_id, target):
    """Set the scoped target of a current task fixture."""
    conn.execute(
        text(
            "UPDATE CFG_TASKS SET TARGET_TABLE_ID=:target, TARGET_ACTIVE_FLAG='Y' WHERE "
            "TASK_ID=:task"
        ),
        {"task": task_id, "target": add_table(conn, target) if target else None},
    )


@configured_project
def finalize_pipeline(engine, config, pipeline_code, *, hooks=None):
    """Finalize the explicit active run for outcome and publication fixtures."""
    from etl_craft.engine.repository.pipelines import resolve_pipeline_id
    from etl_craft.engine.runlog import select_run
    from etl_craft.execution.run_finish import finalize
    from etl_craft.execution.run_start import load_pipeline
    from etl_craft.execution.run_types import PipelineRun, default_hooks

    with engine.connect() as conn:
        pipeline_id = resolve_pipeline_id(conn, pipeline_code)
        run_id = select_run(conn, pipeline_id).pipeline_run_id
        detail, graph, codes = load_pipeline(conn, pipeline_id, run_id=run_id)
    return finalize(
        engine,
        PipelineRun(pipeline_code, pipeline_id, run_id, graph, codes, detail.sla_in_hours),
        hooks or default_hooks(config, engine),
    )


def hide_from_viewers(conn, *codes, project_id=1):
    """Limit the viewer audience to the project's pipelines other than ``codes``.

    Grants only add access, so a pipeline is hidden by replacing the audience's project-wide
    grant with grants on the pipelines that stay visible.
    """
    conn.execute(
        text(
            "UPDATE CFG_ACCESS_BINDINGS SET ACTIVE_FLAG='N' WHERE PROJECT_ID=:p AND "
            "GRANTEE_ROLE='viewer' AND PIPELINE_CODE IS NULL AND TAG IS NULL"
        ),
        {"p": project_id},
    )
    visible = conn.execute(
        text("SELECT PIPELINE_CODE AS code FROM CFG_PIPELINES WHERE PROJECT_ID=:p"),
        {"p": project_id},
    ).scalars()
    for code in set(visible) - set(codes):
        conn.execute(
            text(
                "INSERT INTO CFG_ACCESS_BINDINGS (PROJECT_ID,PIPELINE_CODE,GRANTEE_ROLE,ROLE_NAME) "
                "VALUES (:p,:code,'viewer','CAN_VIEW')"
            ),
            {"p": project_id, "code": code},
        )
