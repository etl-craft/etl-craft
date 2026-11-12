"""Closed provenance states and relational mapping operators."""

from enum import StrEnum


class LineageState(StrEnum):
    """The provenance of documented column and table paths."""

    DERIVED = "derived"
    DECLARED = "declared"
    UNAVAILABLE = "unavailable"


class MappingKind(StrEnum):
    """Relational operators represented in a task mapping."""

    SOURCE = "source"
    JOIN = "join"
    FILTER = "filter"
    AGGREGATE = "aggregate"
    SET = "set"


class DefinitionKind(StrEnum):
    """The definition objects connected by a catalog dependency."""

    TASK = "task"
    PIPELINE = "pipeline"
