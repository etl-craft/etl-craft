"""Start a pipeline's next run when its last run ended in a status its condition names."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.engine import Engine, Row

from etl_craft.core.actor import acting_as, current_actor
from etl_craft.core.enums import InterventionAction, RunStatus, TriggerKind
from etl_craft.core.errors import MetadataFileError, StaleTransitionError
from etl_craft.core.restart import restart_statuses
from etl_craft.core.time import as_utc
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.intervention_rows import record_intervention
from etl_craft.engine.run_creation import RunCreation, create
from etl_craft.services.operations import OperationContext

logger = logging.getLogger("etl_craft.controller.restarts")

COOLDOWN = timedelta(seconds=15)
"""A restart is made no sooner than this after the run it follows ended, so a run that ends at
once cannot spin."""


class Restarts:
    """Restart each pipeline whose latest run ended in a listed status, at most once per run."""

    def __init__(self) -> None:
        """Remember the bad values already reported, so a bad row is not logged every tick."""
        self.reported: set[tuple[int, str]] = set()

    def refresh(
        self, ctx: OperationContext, now: datetime, stop: threading.Event | None = None
    ) -> None:
        """Queue the next run of every pipeline that is due one, in short transactions."""
        allowed = restart_statuses(ctx.config.allowed_auto_restarts)
        if not allowed:
            return
        with ctx.engine.connect() as conn:
            rows = conn.execute(statement(conn, "controller_restarts")).all()
        with acting_as(ctx.actor):
            for row in rows:
                if stop is not None and stop.is_set():
                    return
                if self._due(row, allowed, now):
                    _restart(ctx.engine, row)

    def _due(
        self, row: Row[tuple[object, ...]], allowed: frozenset[RunStatus], now: datetime
    ) -> bool:
        try:
            wanted = restart_statuses(str(row.auto_restart_condition))
        except MetadataFileError as error:
            key = (int(row.pipeline_id), str(row.auto_restart_condition))
            if key not in self.reported:
                self.reported.add(key)
                logger.error("pipeline %s: no restart; %s", row.pipeline_code, error)
            return False
        status = RunStatus(row.last_status)
        try:
            project = restart_statuses(str(row.project_allowed))
        except MetadataFileError as error:
            key = (-int(row.pipeline_id), str(row.project_allowed))
            if key not in self.reported:
                self.reported.add(key)
                logger.error(
                    "pipeline %s: no restart; project setting: %s", row.pipeline_code, error
                )
            return False
        return (
            status in wanted
            and status in allowed
            and status in project
            and now >= as_utc(row.ended_at) + COOLDOWN
        )


def _restart(engine: Engine, row: Row[tuple[object, ...]]) -> None:
    """Commit the next run and why it started; a second controller's attempt loses on the key."""
    try:
        with engine.begin() as conn:
            run_id = create(
                conn,
                int(row.pipeline_id),
                current_actor(),
                RunCreation(
                    trigger_kind=TriggerKind.RESTART,
                    run_key=f"restart:{row.last_run_id}",
                    status=RunStatus.QUEUED,
                ),
            )
            record_intervention(
                conn,
                pipeline_id=int(row.pipeline_id),
                pipeline_run_id=run_id,
                action=InterventionAction.NEW_RUN,
                reason=f"restart after run {row.last_run_id} ended {row.last_status}",
                requested_by=current_actor().name,
                to_status=RunStatus.QUEUED,
            )
    except StaleTransitionError:
        logger.info("pipeline %s: run %s already restarted", row.pipeline_code, row.last_run_id)
