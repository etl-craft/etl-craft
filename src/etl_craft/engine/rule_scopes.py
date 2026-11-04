"""Resolve upstream row-rule decisions through admitted metadata and exact runs."""

from sqlalchemy.engine import Connection

from etl_craft.core.enums import BusinessRuleLevel, DependencyType, Handler, RunStatus
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.rule_flags import KEY_CAP, RuleScope
from etl_craft.core.text import split_object_ref
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.business_rules import BusinessRule, fetch_business_rules_for_task
from etl_craft.engine.repository.tasks import fetch_task_execution_detail
from etl_craft.engine.repository.validation import fetch_task_dependency_edges


def rules(conn: Connection, task_id: int, scope: RuleScope) -> tuple[int, list[BusinessRule]]:
    """Require a direct same-pipeline SUCCESS edge and one unambiguous row-key contract."""
    task = fetch_task_execution_detail(conn, task_id)
    label = f"{task.pipeline_code}.{task.task_code}: {scope.token}"
    edges = [
        e
        for e in fetch_task_dependency_edges(conn)
        if e.label == f"{task.pipeline_code}.{task.task_code}"
        and e.depends_on_task_code == scope.task
        and e.depends_on_pipeline_id == task.pipeline_id
        and e.dependency_type == DependencyType.SUCCESS
        and e.depends_on_handler == Handler.BUSINESS_RULES
        and e.depends_on_task_active
    ]
    if len(edges) != 1:
        raise SqlGuardError(
            f"{label}: expected one same-pipeline active BUSINESS_RULES SUCCESS dependency; "
            "remedy: add that CFG_TASK_DEPENDENCY edge before using the token"
        )
    upstream = edges[0].depends_on_task_id
    selected = [
        r
        for r in fetch_business_rules_for_task(conn, upstream)
        if r.business_rule_level == BusinessRuleLevel.ROW and r.business_rule_type in scope.types
    ]
    contracts = {(r.target_table, r.business_rule_key_column) for r in selected}
    if len(contracts) != 1 or any(not r.target_active for r in selected):
        raise SqlGuardError(
            f"{label}: expected selected ROW rules on one active target and key column; "
            "remedy: name a rules task with one unambiguous target/key contract"
        )
    return upstream, selected


def keys(conn: Connection, task_id: int, run_id: int, scope: RuleScope) -> tuple[str, ...]:
    """Never expose flags from another pipeline run, target or upstream task."""
    upstream, selected = rules(conn, task_id, scope)
    task = fetch_task_execution_detail(conn, task_id)
    statuses = conn.execute(
        statement(conn, "task_statuses_for_run"),
        {
            "pipeline_id": task.pipeline_id,
            "pipeline_run_id": run_id,
        },
    )
    if not any(row.task_id == upstream and row.status == RunStatus.SUCCESS for row in statuses):
        raise SqlGuardError(
            f"{task.pipeline_code}.{task.task_code}: {scope.token}: expected committed SUCCESS "
            "of the rules task in this pipeline run; remedy: complete that upstream task first"
        )
    found: set[str] = set()
    for rule in selected:
        catalog, schema, table = split_object_ref(rule.target_table, param_name="rule target")
        result = conn.execute(
            statement(conn, "rule_scope_keys"),
            {
                "pipeline_run_id": run_id,
                "task_id": upstream,
                "rule_id": rule.business_rule_id,
                "rule_type": rule.business_rule_type,
                "catalog_name": catalog or "",
                "schema_name": schema,
                "table_name": table,
            },
        )
        try:
            for row in result:
                found.add(str(row.rule_key))
                if len(found) > KEY_CAP:
                    raise SqlGuardError(
                        f"{scope.token}: key count {len(found)} exceeds cap {KEY_CAP}; "
                        "remedy: reduce the source batch or split it into smaller runs"
                    )
        finally:
            result.close()
    return tuple(sorted(found))
