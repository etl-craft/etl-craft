"""Single-target merge sources and version changes."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


def numbered_source(source: str, expression: str, column: str = "ROW_ID") -> str:
    """Allocate computed identifiers in the target statement's source."""
    return f"(SELECT numbered.*, {expression} AS {column} FROM {source} numbered)"


def keyed_source(target: str, stage: str, keys: tuple[str, ...], base: str) -> str:
    """Allocate new-key identities without multiplying duplicate existing target keys."""
    match = " AND ".join(f"found.{key}=src.{key}" for key in keys)
    missing = f"found.{keys[0]} IS NULL"
    return (
        f"(SELECT src.*, CASE WHEN {missing} THEN {base} + "
        f"CAST(ROW_NUMBER() OVER (PARTITION BY {missing} ORDER BY NULL) AS BIGINT) "
        f"END AS ROW_ID FROM {stage} src LEFT JOIN "
        f"(SELECT DISTINCT {', '.join(keys)} FROM {target}) found ON {match})"
    )


def internal_column(columns: Sequence[str], name: str) -> str:
    """Keep staging controls distinct from every user column, including quoted case."""
    existing = {column.lower() for column in columns}
    while name.lower() in existing:
        name += "_"
    return name


@dataclass(frozen=True)
class VersionMerge:
    """Close physical versions and insert their successors in the same target statement."""

    target: str
    stage: str
    keys: tuple[str, ...]
    columns: tuple[str, ...]
    condition: str

    @property
    def matched(self) -> str:
        """Name the source's existing physical identity."""
        return internal_column(self.columns, "__etl_match_row_id")

    @property
    def inserting(self) -> str:
        """Name the source's insertion discriminator."""
        return internal_column(self.columns, "__etl_insert_version")

    @property
    def allocated(self) -> str:
        """Name a computed successor identity."""
        return internal_column(self.columns, "__etl_new_row_id")

    def source(self) -> str:
        """Each old ROW_ID matches once; every successor is an unmatched source row."""
        key = " AND ".join(f"t.{column}=s.{column}" for column in self.keys)
        active = f"{key} AND t.ACTIVE_FLAG='Y'"
        close = (
            f"SELECT s.*, t.ROW_ID AS {self.matched}, FALSE AS {self.inserting} "
            f"FROM {self.stage} s JOIN {self.target} t ON {active} "
            f"WHERE {self.condition}"
        )
        insert = (
            f"SELECT s.*, CAST(NULL AS BIGINT) AS {self.matched}, TRUE AS {self.inserting} "
            f"FROM {self.stage} s WHERE NOT EXISTS (SELECT 1 FROM {self.target} t "
            f"WHERE {active} AND NOT ({self.condition}))"
        )
        return f"({close} UNION ALL {insert})"

    def counts(self) -> str:
        """Measure business changes rather than provider-specific MERGE rowcounts."""
        return (
            f"SELECT COALESCE(SUM(CASE WHEN {self.inserting} THEN 0 ELSE 1 END),0) "
            f"AS closed, COALESCE(SUM(CASE WHEN {self.inserting} THEN 1 ELSE 0 END),0) "
            f"AS inserted FROM {self.source()} changes"
        )

    def statement(
        self, source: str, assignments: Mapping[str, str], insert: tuple[str, str]
    ) -> str:
        """Only the closing source row matches an existing target version."""
        updated = ", ".join(f"{column}={value}" for column, value in assignments.items())
        columns, values = insert
        return (
            f"MERGE INTO {self.target} t USING {source} s ON t.ROW_ID=s.{self.matched} "
            f"WHEN MATCHED THEN UPDATE SET {updated} "
            f"WHEN NOT MATCHED AND s.{self.inserting} THEN INSERT ({columns}) VALUES ({values})"
        )


def matched_merge(
    target: str, source: str, assignments: Mapping[str, str], keys: tuple[str, ...] = ("ROW_ID",)
) -> str:
    """Publish a matched target update in one atomic statement."""
    updated = ", ".join(f"{column}={value}" for column, value in assignments.items())
    match = " AND ".join(f"t.{c}=s.{c}" for c in keys)
    return (
        f"MERGE INTO {target} t USING {source} s ON {match} WHEN MATCHED THEN UPDATE SET {updated}"
    )


def delete_merge(
    target: str, source: str, keys: tuple[str, ...], *, null_safe: bool = False
) -> str:
    """Delete each matched target row with one source row per key."""
    operator = " IS NOT DISTINCT FROM " if null_safe else "="
    match = " AND ".join(f"t.{c}{operator}s.{c}" for c in keys)
    return f"MERGE INTO {target} t USING {source} s ON {match} WHEN MATCHED THEN DELETE"


def rehash_source(target: str, expression: str, metadata: str, fingerprint: str) -> str:
    """Hash maintenance changes no business or ordinary audit value."""
    return (
        f"(SELECT t.ROW_ID AS ROW_ID,{expression} AS new_hash,{metadata} AS protection,"
        f"{fingerprint} AS fingerprint FROM {target} t)"
    )
