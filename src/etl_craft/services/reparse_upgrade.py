"""Automatic baselines for projects that predate stored pipeline re-parses."""

import json
from typing import TYPE_CHECKING

from sqlalchemy.engine import Connection, Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ApiRole, YesNo
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import selected_project
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.reparse_models import ReparseResults

if TYPE_CHECKING:
    from etl_craft.services.doctor import Check


def reparse_checks(conn: Connection, project_id: int) -> list["Check"]:
    """List invalid baselines without hiding pipelines that retain a runnable version."""
    from etl_craft.services.doctor import Check, Status

    checks = []
    for row in conn.execute(statement(conn, "reparse_doctor"), {"project_id": project_id}):
        findings = [] if row.findings is None else json.loads(row.findings)
        detail = "; ".join(str(f["message"]) for f in findings) or "no re-parse recorded"
        blocked = not row.has_baseline or row.block_on_reparse_error == YesNo.YES
        state = (
            "no version has passed yet" if not row.has_baseline else "last good version retained"
        )
        checks.append(
            Check(
                f"Pipeline re-parse {row.pipeline_code}",
                Status.FAIL if blocked else Status.WARN,
                f"{state}; {detail}; correct the findings and run `etl-craft pipelines re-parse`",
            )
        )
    return checks


def initialize(engine: Engine, config: ConnectorConfig) -> ReparseResults:
    """Use this project's explicit connector; never infer another project's files."""
    from etl_craft.services.operations.pipeline_reparse import initialize_missing

    with engine.connect() as conn:
        project = conn.execute(
            statement(conn, "project_by_code"), {"code": config.project}
        ).one_or_none()
    if project is None:
        return ReparseResults(())
    project_id = int(project.project_id)
    with selected_project(project_id):
        return initialize_missing(
            OperationContext(
                engine,
                config,
                SYSTEM_ACTOR,
                role=ApiRole.ADMIN,
                project=config.project,
                project_id=project_id,
            )
        )
