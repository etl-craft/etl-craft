"""Record the SQL every warehouse dialect writes for each action, with no warehouse.

A ``GoldenSession`` is the real ``Session`` with its catalog reads answered from a fixed table
shape; a ``RecordingConnection`` keeps every statement the action and its dialect send. The
recorded text is compared with ``tests/fixtures/golden_sql/<dialect>.sql``, so a dialect change
that alters generated SQL is seen without a cloud run.
"""

from __future__ import annotations

import re
from collections import namedtuple
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from etl_craft.config import ConnectionProfile, ConnectorConfig, SourceConfig
from etl_craft.core.enums import RunStatus, SqlAction, TableFormat
from etl_craft.core.errors import EtlCraftError
from etl_craft.dialects.warehouse import WarehouseDialect
from etl_craft.engine.repository.tasks import TargetTask
from etl_craft.engine.task_store import TaskState
from etl_craft.handlers.registry import TaskContext
from etl_craft.handlers.sql import _apply
from etl_craft.handlers.sql.context import ActionContext
from etl_craft.handlers.sql.session import ROW_ID_COLUMN, Session
from etl_craft.handlers.sql.spec import read_sql_task
from etl_craft.handlers.sql.tables import AUDIT_COLUMNS

GOLDEN = Path(__file__).parent / "golden_sql"
SELECT = "SELECT 1 AS id, 'a' AS name, CAST(2.50 AS DECIMAL(10,2)) AS amount"
BUSINESS = (("id", "BIGINT", 19, 0), ("name", "VARCHAR", None, None), ("amount", "DECIMAL", 10, 2))
MERGE = {"SELECT_QUERY": SELECT, "MERGE_KEY": "id", "MERGE_COMPARE_COLUMNS": "name|amount"}
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@dataclass(frozen=True)
class Scenario:
    """One action on a target that exists or not."""

    name: str
    params: Mapping[str, str]
    exists: bool
    writer: str | None = None
    """The action whose managed columns the existing target has; the scenario's own by default."""


SCENARIOS = (
    Scenario("create_table", {"SQL_ACTION": "CREATE_TABLE", "SELECT_QUERY": SELECT}, False),
    Scenario("create_table_replace", {"SQL_ACTION": "CREATE_TABLE", "SELECT_QUERY": SELECT}, True),
    Scenario("overwrite_table", {"SQL_ACTION": "OVERWRITE_TABLE", "SELECT_QUERY": SELECT}, True),
    Scenario("append_table", {"SQL_ACTION": "APPEND_TABLE", "SELECT_QUERY": SELECT}, True),
    Scenario(
        "scd1_merge",
        {**MERGE, "SQL_ACTION": "SCD1_MERGE"},
        True,
    ),
    Scenario(
        "scd2_merge",
        {**MERGE, "SQL_ACTION": "SCD2_MERGE"},
        True,
    ),
    Scenario(
        "delete_rows",
        {"SQL_ACTION": "DELETE_ROWS", "SELECT_QUERY": "SELECT 1 AS id", "MERGE_KEY": "id"},
        True,
        SqlAction.SCD1_MERGE,
    ),
    Scenario(
        "delete_rows_hard",
        {
            "SQL_ACTION": "DELETE_ROWS",
            "SELECT_QUERY": "SELECT 1 AS id",
            "MERGE_KEY": "id",
            "HARD_DELETE": "true",
        },
        True,
        SqlAction.SCD1_MERGE,
    ),
    Scenario("drop_table", {"SQL_ACTION": "DROP_TABLE"}, True),
    Scenario("create_view", {"SQL_ACTION": "CREATE_VIEW", "SELECT_QUERY": SELECT}, False),
    Scenario(
        "setup_table",
        {"SQL_ACTION": "SETUP_TABLE", "SELECT_QUERY": SELECT, "SETUP_FOR": "SCD2_MERGE"},
        False,
    ),
)


class Result:
    """Enough of a SQLAlchemy result for the session and dialect reads."""

    def __init__(self, rows: Sequence[tuple[Any, ...]] = (), keys: Sequence[str] = ()) -> None:
        row = namedtuple("Row", keys) if keys else None  # type: ignore[misc]
        self.rows = [row(*r) if row else r for r in rows]
        self._keys = list(keys)
        self.rowcount = 0
        self.returns_rows = True

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        return iter(self.rows)

    def all(self) -> list[tuple[Any, ...]]:
        return self.rows

    def first(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def one_or_none(self) -> tuple[Any, ...] | None:
        return self.first()

    def one(self) -> tuple[Any, ...]:
        return self.rows[0]

    def scalar(self) -> Any:
        return self.rows[0][0] if self.rows else None

    scalar_one_or_none = scalar

    def scalar_one(self) -> Any:
        return self.rows[0][0] if self.rows else 0

    def scalars(self) -> Iterator[Any]:
        return iter(row[0] for row in self.rows)

    def keys(self) -> list[str]:
        return self._keys

    def mappings(self) -> list[dict[str, Any]]:
        return [dict(zip(self._keys, row, strict=False)) for row in self.rows]


DEFINITION = (
    "CREATE TABLE lake.sales.orders (id BIGINT, name VARCHAR, amount DECIMAL(10,2), "
    "PIPELINE_RUN_ID BIGINT, PIPELINE_ID BIGINT, TASK_RUN_ID BIGINT, ROW_ID BIGINT)"
)


ICEBERG = {
    "format-version": 2,
    "default-spec-id": 0,
    "partition-specs": [{"spec-id": 0, "fields": []}],
    "current-schema-id": 0,
    "schemas": [{"schema-id": 0, "fields": [{"id": 1, "name": "id", "required": False}]}],
    "default-sort-order-id": 0,
    "properties": {},
}


def answer(sql: str) -> Result:
    """Answer the reads actions make directly; every other statement returns no rows."""
    upper = sql.upper()
    if upper.startswith("SELECT COUNT(*) FROM") or upper.startswith("SELECT COALESCE(MAX(ROW_ID"):
        return Result([(1,)])
    if "NULL_KEYS" in upper:
        keys = ("source_rows", "duplicate_rows", "null_keys", "duplicate_keys", "new_keys")
        return Result([(1, 0, 0, 0, 1, None)], (*keys, "locked_type"))
    if "AS CLOSED" in upper and "AS INSERTED" in upper:
        return Result([(1, 1)], ("closed", "inserted"))
    if "FROM PG_CLASS" in upper:
        return Result([("r", None)], ("relkind", "comment"))
    if "ICEBERG_LOAD_TABLE_RESPONSE" in upper:
        return Result([(ICEBERG,)], ("metadata",))
    if "SHOW CREATE TABLE" in upper or "GET_DDL" in upper:
        return Result([(DEFINITION,)], ("definition",))
    return Result()


class RecordingConnection:
    """Keep each statement's text; answer every read with no rows."""

    def __init__(self, sqlalchemy_name: str) -> None:
        self.statements: list[str] = []
        self.dialect = SimpleNamespace(name=sqlalchemy_name, server_version_info=(17, 0))

    def execute(self, statement: object, parameters: object = None) -> Result:
        sql = str(statement)
        self.statements.append(sql)
        return answer(sql)

    exec_driver_sql = execute

    def commit(self) -> None:
        return None

    def in_transaction(self) -> bool:
        return True


class GoldenSession(Session):
    """The real session, reading a fixed catalog instead of the warehouse."""

    def __init__(
        self, conn: RecordingConnection, dialect: WarehouseDialect, action: str, scenario: Scenario
    ) -> None:
        super().__init__(
            conn,  # type: ignore[arg-type]
            dialect,
            catalog="lake",
            action=action,
            target_object="sales.orders",
            task_run_id=7,
            params={},
        )
        self.token = "golden"
        self.exists = scenario.exists
        audit = AUDIT_COLUMNS.get(scenario.writer or action, ())
        self.shape = [
            *[(self.cased(n), kind, p, s, "YES") for n, kind, p, s in BUSINESS],
            ("PIPELINE_RUN_ID", "BIGINT", None, None, "YES"),
            *[(n, dialect.audit_column_type(n), None, None, "YES") for n in audit],
            (ROW_ID_COLUMN, "BIGINT", None, None, "YES"),
        ]

    def cased(self, name: str) -> str:
        return name.upper() if self.dialect.identifier_case == "upper" else name

    def _shape(self, name: str):  # type: ignore[no-untyped-def]
        if name.lower() != self.target.lower():
            return [(self.cased(n), kind, p, s, "YES") for n, kind, p, s in BUSINESS]
        return self.shape if self.exists else ()

    def relation_types(self, names: tuple[str, ...]) -> dict[int, str]:
        return {0: "BASE TABLE"} if self.exists and names[0].lower() == self.target.lower() else {}

    def prime_target(self) -> None:
        return None

    def describe_select(self, sql: str) -> list[tuple[str, str]] | None:
        own = type(self.dialect).describe_select is not WarehouseDialect.describe_select
        if not own or self.dialect.spec.table_format == TableFormat.ICEBERG:
            return None
        return [(self.cased(name), kind) for name, kind, *_ in BUSINESS]

    def column_types(self, name: str) -> dict[str, str]:
        return {column.lower(): kind for column, kind, *_ in self._shape(name)}

    def check_target_format(self) -> None:
        return None


STATE = TaskState(offset=None, rules=(), peers=(), peer_statuses={}, merge_conflict=None)
DROP_STATE = TaskState(
    offset=None,
    rules=(),
    peers=(TargetTask(3, "C", SqlAction.CREATE_TABLE),),
    peer_statuses={"3": RunStatus.SUCCESS},
    merge_conflict=None,
)


def context(params: Mapping[str, str], project: Path) -> TaskContext:
    engine = ConnectionProfile("ENGINE", "dev", "jdbc:sqlite:e.db", "", "NONE")
    config = ConnectorConfig(
        source=SourceConfig(type="environment"),
        engine=engine,
        config_path=project / "craft-connector.yml",
    )
    return TaskContext(
        config=config,
        pipeline_id=1,
        pipeline_code="P",
        task_id=2,
        task_code="T",
        pipeline_run_id=42,
        task_run_id=7,
        attempt=1,
        handler="SQL",
        refresh_type="FULL",
        task_params={"TARGET_OBJECT": "sales.orders", **params},
        started_at=NOW,
    )


def record(dialect: WarehouseDialect, scenario: Scenario, project: Path) -> list[str]:
    """Run one scenario's action and return the statements it sent."""
    task_context = context(scenario.params, project)
    task = read_sql_task(task_context)
    conn = RecordingConnection(dialect.spec.sqlalchemy_name)
    with patch("etl_craft.handlers.sql.session.event"):
        session = GoldenSession(conn, dialect, task.action, scenario)
        session.protection_store = Mock()
        store = Mock()
        store.target.return_value.hash_version = 2
        action = ActionContext(
            task=task,
            context=task_context,
            store=store,
            user="golden",
            now=NOW,
            state=DROP_STATE if task.action == SqlAction.DROP_TABLE else STATE,
        )
        _apply(session, action)
        session.sweep()
    return [normalize(s) for s in conn.statements]


def normalize(sql: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", sql.strip())


def render(dialect: WarehouseDialect, project: Path) -> str:
    """Every scenario's statements for ``dialect``, one section per scenario."""
    sections = []
    for scenario in SCENARIOS:
        try:
            statements = [f"{s};" for s in record(dialect, scenario, project)]
        except EtlCraftError as error:
            statements = [f"-- refused: {error}"]
        sections.append(f"-- {scenario.name}\n" + "\n\n".join(statements))
    return "\n\n".join(sections) + "\n"
