"""Read ``AUTO_RESTART_CONDITION`` and ``Orchestration.Allowed_auto_restarts``.

Both name what may start a pipeline on its own: ``SCHEDULE`` (its ``RUN_SCHEDULE``), run endings
(``SUCCESS``, ``SKIPPED``, ``FAILURE``, or ``ALWAYS`` for all three), or ``NONE``.
"""

from etl_craft.core.enums import AutoRestartCondition, RunStatus
from etl_craft.core.errors import MetadataFileError

_ENDINGS = (
    AutoRestartCondition.SUCCESS,
    AutoRestartCondition.SKIPPED,
    AutoRestartCondition.FAILURE,
)
_STATUS = {
    AutoRestartCondition.SUCCESS: RunStatus.SUCCESS,
    AutoRestartCondition.SKIPPED: RunStatus.SKIPPED,
    AutoRestartCondition.FAILURE: RunStatus.FAILED,
}
ALLOWED = ", ".join(AutoRestartCondition)
EVERYTHING = "SCHEDULE|ALWAYS"
"""The default of ``Allowed_auto_restarts``: nothing is suppressed."""


def parse_auto_restart(value: str) -> str:
    """Return ``value`` in its canonical form, ``SCHEDULE`` then endings in order, or refuse it.

    The value is ``NONE``, or ``|``-separated: ``SCHEDULE``, and either ``ALWAYS`` or any of
    ``SUCCESS``, ``SKIPPED`` and ``FAILURE``. ``MetadataFileError`` names the value and the remedy.
    """
    parts = value.split("|")
    unknown = [part for part in parts if part not in set(AutoRestartCondition)]
    if unknown:
        raise MetadataFileError(
            f"{value!r} has {unknown[0]!r}, which is not one of {ALLOWED}; write NONE, or "
            "values joined with |, such as SCHEDULE|SUCCESS"
        )
    if len(set(parts)) != len(parts):
        raise MetadataFileError(f"{value!r} repeats a value; name each of {ALLOWED} once")
    if AutoRestartCondition.NONE in parts and len(parts) > 1:
        raise MetadataFileError(f"{value!r} combines NONE with another value; use NONE alone")
    if AutoRestartCondition.ALWAYS in parts and set(_ENDINGS) & set(parts):
        raise MetadataFileError(
            f"{value!r} names an ending beside ALWAYS, which already includes SUCCESS, SKIPPED "
            "and FAILURE; write ALWAYS alone, or the endings you mean"
        )
    ordered = (
        AutoRestartCondition.NONE,
        AutoRestartCondition.SCHEDULE,
        *_ENDINGS,
        AutoRestartCondition.ALWAYS,
    )
    return "|".join(part for part in ordered if part in parts)


def schedule_allowed(value: str) -> bool:
    """Return whether ``SCHEDULE`` is named, so the pipeline's ticks may start runs."""
    return AutoRestartCondition.SCHEDULE in parse_auto_restart(value).split("|")


def restart_statuses(value: str) -> frozenset[RunStatus]:
    """Return the run statuses whose ending may start the next run; none without any ending."""
    parts = parse_auto_restart(value).split("|")
    if AutoRestartCondition.ALWAYS in parts:
        return frozenset(_STATUS.values())
    return frozenset(_STATUS[AutoRestartCondition(part)] for part in parts if part in set(_ENDINGS))
