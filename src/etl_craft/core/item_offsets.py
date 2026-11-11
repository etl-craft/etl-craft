"""Own-key provisional partition positions shared by scripts and fenced stores."""

from collections.abc import Mapping

from etl_craft.core.enums import OffsetType, ScriptKind
from etl_craft.core.errors import PermanentError


def position(
    key: str,
    values: object,
    datatype: str,
    committed: Mapping[str, int] | None,
    committed_type: str | None,
    kind: str,
) -> int:
    """Refuse foreign keys, offset types and backwards provisional positions."""
    found = list(values) if isinstance(values, Mapping) else values
    if (
        datatype != OffsetType.PARTITIONS
        or not isinstance(values, Mapping)
        or set(values) != {key}
        or kind != ScriptKind.INGESTION
        or (committed_type is not None and committed_type != OffsetType.PARTITIONS)
    ):
        raise PermanentError(
            f"item {key}: offset type={datatype}, keys found={found!r}, "
            f"task offset type={committed_type}; "
            f"expected PARTITIONS with exactly key {key!r} on a PARTITIONS ingestion task; "
            "return only this item's partition position"
        )
    value = values[key]
    if type(value) is not int or not 0 <= value < 2**63:
        raise PermanentError(
            f"item {key}: position={value!r}; expected a nonnegative BIGINT position "
            f"for key {key!r}; correct the item offset"
        )
    before = committed.get(key) if committed is not None else None
    if before is not None and value < before:
        raise PermanentError(
            f"item {key}: partition {key!r} returned position {value}, behind committed "
            f"position {before}; expected a position that never moves backwards; "
            "return the next consumed position or deliberately reset the task offset "
            "with etl-craft mark"
        )
    return value
