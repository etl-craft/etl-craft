"""Stream rows to bounded scratch storage before one atomic landing publication."""

from collections.abc import Iterable, Iterator, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl_craft.core.errors import HandlerError
from etl_craft.core.faults import fault_point
from etl_craft.core.landing import LandingWrite
from etl_craft.core.text import sha256_hex
from etl_craft.dialects.warehouse.base import WarehouseDialect
from etl_craft.dialects.warehouse.copying import MAX_BOUND_VALUES
from etl_craft.dialects.warehouse.landing import TAGS, columns, publish_statements, stage_insert

BATCH_BYTES = 256 * 1024
ROW_BYTES = 16 * 1024 * 1024


def batches(
    rows: Iterable[Mapping[str, object]], names: tuple[str, ...]
) -> Iterator[list[tuple[object, ...]]]:
    """Bound each batch by bind values and bytes independently of input length."""
    chunk: list[tuple[object, ...]] = []
    used = 0
    width = max(1, MAX_BOUND_VALUES // len(names))
    for index, row in enumerate(rows, 1):
        if set(row) != set(names):
            raise HandlerError(
                f"replace_landing row {index}: columns {sorted(row)}; expected "
                f"{names}; remedy: supply exactly the declared business columns"
            )
        values = tuple(row[name] for name in names)
        size = sum(
            len(v) * 4 if isinstance(v, str) else len(v) if isinstance(v, bytes) else 64
            for v in values
        )
        if size > ROW_BYTES:
            raise HandlerError(
                f"replace_landing row {index}: {size} bytes exceeds {ROW_BYTES}; "
                "remedy: reduce the individual source record"
            )
        if chunk and (used + size > BATCH_BYTES or len(chunk) >= width):
            yield chunk
            chunk, used = [], 0
        chunk.append(values)
        used += size
    if chunk:
        yield chunk


def publish(
    conn: Connection,
    dialect: WarehouseDialect,
    write: LandingWrite,
    rows: Iterable[Mapping[str, object]],
) -> int:
    """Staging may commit independently; only publication changes the live target."""
    kinds = columns(dialect, write)
    target = write.contract.target
    actual = dialect.full_column_types(conn, target)
    if "hash_key" in actual or "etl_protection" in actual:
        raise HandlerError(
            f"replace_landing {target}: expected a non-SCD landing table; "
            "remedy: land first, then use a managed merge for protected targets"
        )
    for name, kind in TAGS.items():
        if name not in actual:
            conn.execute(text(dialect.add_column_sql(target, name, kind, target=True)))
    item = "none" if write.item_key is None else "item:" + write.item_key
    bare = f"etl_landing_{write.contract.task_id}_" + sha256_hex(f"{target}:{item}".encode())[:32]
    stage = bare if dialect.temporary_tables else target.rsplit(".", 1)[0] + "." + bare
    body = (
        "SELECT "
        + ", ".join(f"CAST(NULL AS {kind}) AS {name}" for name, kind in kinds.items())
        + " WHERE 1=0"
    )
    stage, ddl = dialect.scratch_ddl(stage, body)
    conn.execute(text(f"DROP TABLE IF EXISTS {stage}"))
    conn.execute(text(ddl))
    count = 0
    try:
        for chunk in batches(rows, tuple(kinds)):
            conn.execute(*stage_insert(stage, kinds, chunk))
            count += len(chunk)
        conn.commit()
        dialect.prepare_landing_publication(conn)
        statements, parameters = publish_statements(conn, dialect, write, stage, kinds, actual)
        fault_point("landing.before_publish")
        for sql in statements:
            conn.execute(text(sql), parameters)
        fault_point("landing.before_commit")
        conn.commit()
        fault_point("landing.after_commit")
        return count
    finally:
        conn.rollback()
        conn.execute(text(f"DROP TABLE IF EXISTS {stage}"))
        conn.commit()
