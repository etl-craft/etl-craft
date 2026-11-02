"""In-row fingerprints and transient lock projections for a protected mutation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtectionSql:
    """Build row-state projections without persistent warehouse side tables."""

    target: str
    state_table: str
    key_hash: str
    cell_hashes: dict[str, str]
    row_hash: str

    def state(self) -> str:
        """Read the transient current-cell projection."""
        return f"SELECT * FROM {self.state_table}"

    def drift(self) -> str:
        """Find rows changed without their committed protection fingerprint."""
        return (
            f"SELECT COUNT(*) FROM {self.target} t WHERE ETL_ROW_FINGERPRINT IS NULL OR "
            f"ETL_ROW_FINGERPRINT IS DISTINCT FROM {self.row_hash}"
        )

    def current(self) -> str:
        """Use the latest physical version, including a deleted key awaiting revival."""
        return (
            f"SELECT * FROM (SELECT t.*, ROW_NUMBER() OVER (PARTITION BY {self.key_hash} "
            f"ORDER BY t.ROW_ID DESC) AS etl_rank FROM {self.target} t) v WHERE etl_rank = 1"
        )

    def protect_stage(
        self, stage: str, columns: tuple[str, ...], *, delete: bool, preserve: bool = False
    ) -> str:
        """Exclude protected rows and overlay locked values before hashing the source."""
        key = self.key_hash.replace("t.", "s.")
        state = self.state()
        lock = f"EXISTS (SELECT 1 FROM ({state}) p WHERE p.key_hash = {key} AND p.locked"
        selection = ", ".join(f"s.{column}" for column in columns)
        if not delete:
            selection = ", ".join(
                f"s.{column}"
                if column.lower() == "locked"
                else f"CASE WHEN {lock} AND p.column_name = '{column.lower()}') "
                f"THEN t.{column} ELSE "
                + (f"COALESCE(s.{column}, t.{column})" if preserve else f"s.{column}")
                + f" END AS {column}"
                for column in columns
            )
        join = "" if delete else f" LEFT JOIN ({self.current()}) t ON {self.key_hash} = {key}"
        row_lock = lock + (")" if delete else " AND p.column_name = '*')")
        return f"SELECT {selection} FROM {stage} s{join} WHERE NOT {row_lock}"

    def prevented(
        self, stage: str, columns: tuple[str, ...], *, delete: bool, preserve: bool = False
    ) -> str:
        """Count attempted protected changes separately from unchanged input."""
        key = self.key_hash.replace("t.", "s.")
        join = f"FROM {stage} s JOIN ({self.current()}) t ON {self.key_hash} = {key} "
        state = self.state()
        if delete:
            return (
                f"SELECT DISTINCT {key} AS key_hash, p.column_name {join} "
                f"JOIN ({state}) p ON p.key_hash = {key} WHERE p.locked"
            )
        return " UNION ALL ".join(
            f"SELECT {key} AS key_hash, '{column.lower()}' AS column_name {join} "
            f"WHERE s.{column} IS DISTINCT FROM t.{column} AND EXISTS "
            f"(SELECT 1 FROM ({state}) p WHERE p.key_hash = {key} AND p.locked "
            f"AND p.column_name IN ('*', '{column.lower()}'))"
            for column in columns
            if column.lower() != "locked"
        )

    def invalid_keys(self, keys: tuple[str, ...], *, scd2: bool) -> str:
        """Reject ambiguous current ownership and NULL business identities before activation."""
        nulls = " OR ".join(f"{key} IS NULL" for key in keys)
        active = "WHERE ACTIVE_FLAG = 'Y'" if scd2 else ""
        return (
            f"SELECT (SELECT COUNT(*) FROM {self.target} WHERE {nulls}) + "
            f"(SELECT COUNT(*) FROM (SELECT {', '.join(keys)} FROM {self.target} {active} "
            f"GROUP BY {', '.join(keys)} HAVING COUNT(*) > 1) d)"
        )


def bound_relation(columns: tuple[tuple[str, str], ...], count: int) -> str:
    """Project bounded metadata rows with explicit types on every provider."""
    return " UNION ALL ".join(
        "SELECT "
        + ", ".join(
            f"CAST(:v_{row}_{index} AS {kind}) AS {name}"
            for index, (name, kind) in enumerate(columns)
        )
        for row in range(count)
    )


def key_membership(target: str, hashed: str, parameters: tuple[str, ...]) -> str:
    """Read only logged-key fingerprints present in the physical target."""
    binds = ",".join(f":{name}" for name in parameters)
    return f"SELECT DISTINCT {hashed} AS key_hash FROM {target} t WHERE {hashed} IN ({binds})"
