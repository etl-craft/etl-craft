"""Erasure boundaries that cannot safely carry a direct personal identifier."""

import json

from sqlalchemy.engine import Engine
from sqlglot import exp

from etl_craft.config import ConnectorConfig
from etl_craft.config.project import project_config, sql_script
from etl_craft.config.targets import active_catalog
from etl_craft.core.definitions import Definition, using
from etl_craft.core.enums import Handler, RefreshType
from etl_craft.core.errors import EtlCraftError
from etl_craft.dialects.query_analysis import read_query
from etl_craft.engine.bundles import Bundle
from etl_craft.engine.erasure_definitions import pinned
from etl_craft.engine.repository.tasks import fetch_all_task_parameters
from etl_craft.engine.repository.validation import fetch_active_tasks, fetch_task_dependency_edges
from etl_craft.handlers.lineage import TaskLineage, script_lineage, table_name
from etl_craft.handlers.sql.spec import read_select, resolve_select
from etl_craft.warehouse.connection import warehouse_dialect


def boundaries(engine: Engine, config: ConnectorConfig) -> tuple[list[TaskLineage], set[str]]:
    """Report opaque dependent Python targets and stop at aggregate queries."""
    with engine.connect() as conn:
        tasks = fetch_active_tasks(conn)
        params = fetch_all_task_parameters(conn)
        dependencies = fetch_task_dependency_edges(conn)
    catalog = active_catalog(config)
    opaque, aggregates = [], set()
    for task in tasks:
        given = params.get(task.task_id, {})
        target = given.get("TARGET_OBJECT")
        if not target:
            continue
        target = table_name(target.split("."), catalog)
        if task.handler == Handler.PYTHON:
            sources = tuple(
                sorted(
                    {
                        table_name(
                            params[d.depends_on_task_id]["TARGET_OBJECT"].split("."), catalog
                        )
                        for d in dependencies
                        if d.label == task.label
                        and params.get(d.depends_on_task_id, {}).get("TARGET_OBJECT")
                    }
                )
            )
            opaque.append(
                TaskLineage(
                    task.label,
                    None,
                    [],
                    error="Opaque Python-script target.",
                    sources=sources,
                    targets=(target,),
                )
            )
        elif task.handler == Handler.SQL:
            try:
                sql, _ = resolve_select(
                    config, given, pipeline_run_id=0, refresh_type=RefreshType.FULL
                )
                query = read_query(sql, warehouse_dialect(config).sqlglot_dialect).root
                if query is not None and (
                    query.find(exp.AggFunc) is not None or query.find(exp.Group) is not None
                ):
                    aggregates.add(target)
            except EtlCraftError:
                # collect() retains the validation refusal as this task's lineage boundary.
                continue
    return opaque, aggregates


def project_graph(
    engine: Engine, config: ConnectorConfig
) -> tuple[Definition, dict[str, TaskLineage]]:
    """Read each task's SQL bytes from its own pinned bundle before tracing the graph."""
    definition, bundles = pinned(engine)
    configs = {}
    with engine.connect() as conn:
        for pipeline, bundle_id in bundles.items():
            configs[pipeline] = (
                config
                if bundle_id is None
                else project_config(
                    config, Bundle.load(conn, bundle_id).materialize(config) / "craft-connector.yml"
                )
            )
    with using(definition), engine.connect() as conn:
        tasks = fetch_active_tasks(conn)
        parameters = fetch_all_task_parameters(conn)
    data = json.loads(definition.text)
    script_results = {}
    for task in tasks:
        params = parameters.get(task.task_id, {})
        if not params.get("SCRIPT_FILE"):
            continue
        project = configs[task.pipeline_code]
        if task.handler == Handler.SQL:
            sql, _ = read_select(project, params)
            for row in data["CFG_TASK_PARAMETERS"]["rows"]:
                if row["task_id"] == task.task_id and row["parameter_name"] == "SCRIPT_FILE":
                    row.update(parameter_name="SELECT_QUERY", parameter_value=sql)
        elif task.handler == Handler.SQL_SCRIPT:
            sql = sql_script(project, params["SCRIPT_FILE"], setting="SCRIPT_FILE").read_text(
                encoding="utf-8"
            )
            script_results[task.label] = script_lineage(sql, task.label, project)
    return Definition.read(json.dumps(data)), script_results
