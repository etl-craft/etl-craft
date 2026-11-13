"""A one-time full refresh: what a run re-reads from the start, and what it may empty first."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FullRefresh:
    """The tasks a run re-reads from the start, and the append targets the operator confirmed.

    ``tasks`` lists task codes, or is ``None`` for every task of the pipeline. A task outside it
    runs as usual. ``empty_targets`` are the ``TARGET_OBJECT`` values of the ``APPEND_TABLE`` tasks
    in scope: each is emptied before its load, because an append would otherwise write every
    source row a second time.
    """

    tasks: tuple[str, ...] | None = None
    empty_targets: tuple[str, ...] = ()

    def covers(self, task_code: str) -> bool:
        """Whether ``task_code`` re-reads from the start in this run."""
        return self.tasks is None or task_code in self.tasks

    def serialize(self) -> str:
        """Write the plan as the JSON stored with the run."""
        return json.dumps(
            {
                "tasks": None if self.tasks is None else list(self.tasks),
                "empty_targets": list(self.empty_targets),
            },
            sort_keys=True,
        )

    @classmethod
    def deserialize(cls, value: str) -> FullRefresh:
        """Read a plan written by ``serialize``."""
        data = json.loads(value)
        tasks = data["tasks"]
        return cls(None if tasks is None else tuple(tasks), tuple(data["empty_targets"]))
