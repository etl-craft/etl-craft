"""Warehouse SQL shared by computed-ID publications."""


def row_number(base: int | str, partition: str = "") -> str:
    """Assign IDs within the selected partition of a materialized source."""
    return f"{base} + CAST(ROW_NUMBER() OVER ({partition}ORDER BY NULL) AS BIGINT)"


def violations_sql(target: str) -> str:
    """Find at most ten IDs beyond the range or duplicated by this write."""
    return (
        f"SELECT ROW_ID AS row_id FROM {target} GROUP BY ROW_ID "
        "HAVING ROW_ID > :end OR (COUNT(*) > 1 AND "
        "(ROW_ID >= :start OR MAX(CASE WHEN COALESCE(TASK_RUN_ID, 0) = :task_run "
        "THEN 1 ELSE 0 END) = 1)) "
        "ORDER BY ROW_ID LIMIT 10"
    )
