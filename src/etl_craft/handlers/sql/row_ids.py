"""Number materialized rows in their writer's ROW_ID range."""

from etl_craft.dialects.warehouse.row_ids import row_number
from etl_craft.handlers.sql.session import Session


def staged_base(session: Session, stage: str, predicate: str = "") -> int:
    """Count the rows that get an ID and return the ID before them."""
    count = session.count(f"SELECT COUNT(*) FROM {stage} {predicate}", step="staged new ROW_IDs")
    return session.row_id_base(count)


def numbered_merge_source(session: Session, stage: str, key_match: str) -> str:
    """Freeze which SCD1 keys are inserts before numbering them."""
    from etl_craft.dialects.warehouse.merges import internal_column

    fresh = internal_column(tuple(name for name, _ in session.columns(stage)), "__etl_insert_key")
    chosen = session.create_scratch(
        session.scratch("scd1_ids"),
        f"SELECT s.*, NOT EXISTS (SELECT 1 FROM {session.target} t WHERE {key_match}) "
        f"AS {fresh} FROM {stage} s",
        step="stage new and existing merge keys",
    )
    base = staged_base(session, chosen, f"WHERE {fresh}")
    return (
        f"(SELECT s.*, CASE WHEN {fresh} THEN {row_number(base, f'PARTITION BY {fresh} ')} "
        f"END AS ROW_ID FROM {chosen} s)"
    )
