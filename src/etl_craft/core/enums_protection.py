"""Closed protection intent and recovery outcomes."""

from enum import StrEnum

from etl_craft.core.enums import Handler


class ProtectionStatus(StrEnum):
    """Name the immutable intent lifecycle outcomes."""

    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ABANDONED = "ABANDONED"


class ProtectionKind(StrEnum):
    """Name mutations whose effects need crash recovery."""

    ENABLE = "ENABLE"
    KEY = "KEY"
    VERSION = "VERSION"
    SOFT_DELETE = "SOFT_DELETE"
    WRITE = "WRITE"
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    REHASH = "REHASH"
    HARD_DELETE = "HARD_DELETE"
    ERASURE = Handler.ERASURE


class ProtectionEvidence(StrEnum):
    """Name the warehouse observation proving a recovery outcome."""

    STAMP_PRESENT = "STAMP_PRESENT"
    STAMP_ABSENT = "STAMP_ABSENT"
    KEYS_ABSENT = "KEYS_ABSENT"
    KEYS_PRESENT = "KEYS_PRESENT"
