"""Managed SQL consumes only committed upstream row decisions in the same run."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from etl_craft.core.errors import SqlGuardError
from etl_craft.handlers import sql
from fixtures.business_rules import add_rule, run_rules
from fixtures.metadata import add_dependency


def check_rule_flags(w):
    from etl_craft.warehouse.connection import warehouse_dialect

    text_type = warehouse_dialect(w.config).string_type
    orders, filtered = "flags_orders_" + uuid4().hex[:10], "flags_filtered_" + uuid4().hex[:10]
    w.run(
        "source",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT=orders,
        SELECT_QUERY="SELECT 1 AS order_id, 5 AS amount "
        "UNION ALL SELECT 2, -3 UNION ALL SELECT 3, 99",
    )
    w.task("rules")
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='BUSINESS_RULES' WHERE TASK_ID=:id"),
            {"id": w.tasks["rules"]},
        )
    add_rule(w, "negative", "SELECT order_id FROM $$rows_in_scope WHERE amount < 0", target=orders)
    add_rule(
        w,
        "large",
        "SELECT order_id FROM $$rows_in_scope WHERE amount > 50",
        target=orders,
        rule_type="REPORT",
    )
    assert run_rules(w).insert_count == 2
    w.finish("rules")
    context = w.task(
        "filtered",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT=w.name(filtered),
        SELECT_QUERY=f"SELECT order_id, amount FROM {w.name(orders)} WHERE "
        f"CAST(order_id AS {text_type}) NOT IN ($$rule_flags(rules, REJECT))",
    )
    with pytest.raises(SqlGuardError, match=r"filtered.*rule_flags.*SUCCESS.*remedy"):
        sql.run(context, w.engine_db)
    assert filtered not in w.tables()
    with w.engine_db.begin() as conn:
        add_dependency(conn, w.pipeline_id, w.tasks["filtered"], w.tasks["rules"])
    assert sql.run(context, w.engine_db).insert_count == 2
    assert w.rows(f"SELECT order_id,amount FROM {w.name(filtered)} ORDER BY order_id") == [
        (1, 5),
        (3, 99),
    ]

    w.new_run()
    assert run_rules(w).insert_count == 0
    w.finish("rules")
    context = w.task(
        "filtered",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT=w.name(filtered),
        SELECT_QUERY=f"SELECT order_id, amount FROM {w.name(orders)} WHERE "
        f"CAST(order_id AS {text_type}) NOT IN ($$rule_flags(rules, REJECT))",
    )
    assert sql.run(context, w.engine_db).insert_count == 3
    assert w.rows(f"SELECT order_id FROM {w.name(filtered)} ORDER BY order_id") == [
        (1,),
        (2,),
        (3,),
    ]

    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_BUSINESS_RULES SET ACTIVE_FLAG='N' WHERE TASK_ID=:id"),
            {"id": w.tasks["rules"]},
        )

    w.execute(f"DROP TABLE {w.name(filtered)}")
    w.execute(f"DROP TABLE {w.name(orders)}")


def check_literal_keys(w):
    """Execute attacker-shaped keys as data and preserve an unrelated control row."""
    from etl_craft.dialects.warehouse.rule_flags import key_set
    from etl_craft.warehouse.connection import warehouse_dialect

    filtered_code = "literal_filtered"
    orders, filtered = "flags_orders_" + uuid4().hex[:10], "flags_filtered_" + uuid4().hex[:10]
    values = ("quote'\\backslash; DROP TABLE victim--", "é😀", "x" * 4096, ":bound")
    dialect = warehouse_dialect(w.config)
    source = key_set(dialect, (*values, "control"))
    w.run(
        "source",
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT=orders,
        SELECT_QUERY=f"SELECT rule_key AS order_id FROM ({source}) source_keys",
    )
    w.task("rules")
    with w.engine_db.begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASKS SET HANDLER='BUSINESS_RULES' WHERE TASK_ID=:id"),
            {"id": w.tasks["rules"]},
        )
    add_rule(
        w,
        "literal",
        "SELECT order_id FROM $$rows_in_scope WHERE order_id <> 'control'",
        target=orders,
    )
    assert run_rules(w).insert_count == len(values)
    w.finish("rules")
    context = w.task(
        filtered_code,
        SQL_ACTION="CREATE_TABLE",
        TARGET_OBJECT=w.name(filtered),
        SELECT_QUERY=f"SELECT order_id FROM {w.name(orders)} WHERE "
        "order_id NOT IN ($$rule_flags(rules, REJECT))",
    )
    with w.engine_db.begin() as conn:
        add_dependency(conn, w.pipeline_id, w.tasks[filtered_code], w.tasks["rules"])
    assert sql.run(context, w.engine_db).insert_count == 1
    assert w.rows(f"SELECT order_id FROM {w.name(filtered)}") == [("control",)]

    w.execute(f"DROP TABLE {w.name(filtered)}")
    w.execute(f"DROP TABLE {w.name(orders)}")
