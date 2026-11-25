"""Reserve computed warehouse identities through the existing target fence."""

from sqlalchemy.engine import Engine

from etl_craft.core.errors import StaleTransitionError, UsageError
from etl_craft.engine.agent_state import fence
from etl_craft.engine.locks import ResourceLock
from etl_craft.engine.queries import statement
from etl_craft.engine.resource_locks import Holder


def reserve_row_ids(
    engine: Engine, lock: ResourceLock, holder: Holder, count: int, maximum: int
) -> int:
    """Commit exactly count identities and return the base preceding the reserved range."""
    subject = f"attempt {holder.attempt_id}, {lock.name}"
    if count < 0 or maximum < 0:
        raise UsageError(
            f"{subject}: count={count}, warehouse MAX(ROW_ID)={maximum}; "
            "expected a nonnegative count and maximum; count the staged insert rows"
        )
    with engine.begin() as conn:
        try:
            if holder.attempt_id is not None:
                fence(conn, holder.attempt_id, holder.owner)
            owned = conn.execute(
                statement(conn, "target_row_id_fence"),
                {"key": lock.key, "holder": holder.holder_id, "owner": holder.owner},
            ).scalar_one_or_none()
            if owned is None:
                raise StaleTransitionError("expected a live lock held by this writer")
        except StaleTransitionError as error:
            raise StaleTransitionError(
                f"{subject}: {error}; acquire the target lock first"
            ) from error
        saved = conn.execute(
            statement(conn, "target_row_id_high_water"), {"key": lock.key}
        ).scalar_one_or_none()
        base = max(maximum, int(saved or 0))
        end = base + count
        if end >= 2**63:
            raise UsageError(
                f"{subject}: reserved end {end} exceeds BIGINT; provide a fresh target"
            )
        conn.execute(statement(conn, "target_row_id_reserve"), {"key": lock.key, "high_water": end})
    return base
