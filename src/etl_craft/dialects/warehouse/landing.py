"""Dialect-owned single-publication replacement of an owned landing batch."""

from collections.abc import Mapping

from sqlalchemy import TextClause, text
from sqlalchemy.engine import Connection
from sqlglot import exp
from sqlglot.errors import SqlglotError

from etl_craft.core.errors import HandlerError
from etl_craft.core.landing import GENERATED_COLUMNS, LandingWrite
from etl_craft.core.text import is_safe_identifier, is_safe_object_ref
from etl_craft.dialects.warehouse.base import WarehouseDialect

TAGS = {"landing_task_id": "BIGINT", "item_key": "VARCHAR(512)"}
RESERVED = GENERATED_COLUMNS


def columns(dialect: WarehouseDialect, write: LandingWrite) -> dict[str, str]:
    """Validate identifiers and declared type syntax independently of row values."""
    if not is_safe_object_ref(write.contract.target):
        raise HandlerError("replace_landing target must be schema.table; correct the declaration")
    result = {}
    for name, kind in write.contract.columns:
        if not is_safe_identifier(name) or name.lower() in RESERVED:
            raise HandlerError(
                f"replace_landing column {name!r}; expected plain "
                "business identifier; remedy: correct CFG_COLUMNS"
            )
        try:
            parsed = exp.DataType.build(kind, dialect=dialect.sqlglot_dialect)
            if parsed.this == exp.DataType.Type.UNKNOWN:
                raise HandlerError(f"column {name}: unknown declared type {kind!r}")
            result[name] = parsed.sql(dialect=dialect.sqlglot_dialect)
        except (SqlglotError, ValueError) as error:
            raise HandlerError(
                f"column {name}: invalid declared type {kind!r}; remedy: correct CFG_COLUMNS"
            ) from error
    return result


def stage_insert(
    stage: str, kinds: Mapping[str, str], rows: list[tuple[object, ...]]
) -> tuple[TextClause, dict[str, object]]:
    """Bound all incoming values and cast against the declared contract."""
    groups = ", ".join(
        "(" + ", ".join(f"CAST(:r{r}c{c} AS {kind})" for c, kind in enumerate(kinds.values())) + ")"
        for r in range(len(rows))
    )
    values = {f"r{r}c{c}": value for r, row in enumerate(rows) for c, value in enumerate(row)}
    return text(f"INSERT INTO {stage} ({', '.join(kinds)}) VALUES {groups}"), values


def publish_statements(
    conn: Connection,
    dialect: WarehouseDialect,
    write: LandingWrite,
    stage: str,
    kinds: Mapping[str, str],
    actual: Mapping[str, str],
) -> tuple[tuple[str, ...], dict[str, object]]:
    """Delete owned old rows and insert new rows with one atomic target MERGE."""
    target = write.contract.target
    parameters: dict[str, object] = {
        "landing_owner": write.contract.task_id,
        "landing_item": write.item_key,
        "pipeline_id": write.pipeline_id,
        "pipeline_run_id": write.pipeline_run_id,
        "task_run_id": write.task_run_id,
    }
    scope = "landing_task_id=:landing_owner"
    if write.item_key is not None:
        scope += " AND item_key=:landing_item"
    inserts = dict(kinds)
    inserts.update(pipeline_id="BIGINT", pipeline_run_id="BIGINT", task_run_id="BIGINT", **TAGS)
    expressions = {name: "n." + name for name in kinds}
    expressions.update(
        pipeline_id=":pipeline_id",
        pipeline_run_id=":pipeline_run_id",
        task_run_id=":task_run_id",
        landing_task_id=":landing_owner",
        item_key=":landing_item",
    )
    for stamp in ("create_date", "update_date"):
        if stamp in actual:
            inserts[stamp] = actual[stamp]
            expressions[stamp] = "CURRENT_TIMESTAMP"
    if not dialect.row_id_generated(conn, target):
        base = conn.execute(text(f"SELECT COALESCE(MAX(row_id),0) FROM {target}")).scalar_one()
        parameters["landing_base"] = int(base)
        inserts["row_id"] = "BIGINT"
        expressions["row_id"] = ":landing_base + CAST(ROW_NUMBER() OVER (ORDER BY NULL) AS BIGINT)"
    deleting = ", ".join(f"CAST(NULL AS {kind}) AS {name}" for name, kind in inserts.items())
    creating = ", ".join(f"{expressions[name]} AS {name}" for name in inserts)
    names = ", ".join(inserts)
    if not dialect.supports_insert_merge(conn):
        return (
            f"DELETE FROM {target} WHERE {scope}",
            f"INSERT INTO {target} ({names}) SELECT {creating} FROM {stage} n",
        ), parameters
    source = (
        f"(SELECT row_id AS landing_match, {deleting} FROM {target} WHERE {scope} "
        f"UNION ALL SELECT CAST(NULL AS BIGINT) AS landing_match, {creating} FROM {stage} n)"
    )
    names = ", ".join(inserts)
    values = ", ".join("s." + name for name in inserts)
    sql = (
        f"MERGE INTO {target} t USING {source} s ON t.row_id=s.landing_match "
        f"WHEN MATCHED THEN DELETE WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({values})"
    )
    return (sql,), parameters
