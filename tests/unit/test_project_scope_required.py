"""Project-owned repository calls require explicit selection."""

import pytest
from sqlalchemy import create_engine

from etl_craft.core.errors import ExitCode, ProjectNotSelectedError
from etl_craft.engine.repository.pipelines import (
    current_project_id,
    resolve_pipeline_id,
    selected_project,
)

pytestmark = pytest.mark.unit


def test_repository_refuses_without_a_selected_project():
    engine = create_engine("sqlite://")
    try:
        with (
            engine.connect() as conn,
            selected_project(None),
            pytest.raises(ProjectNotSelectedError) as caught,
        ):
            resolve_pipeline_id(conn, "LOAD")
        assert caught.value.exit_code is ExitCode.PROJECT_NOT_SELECTED
        for part in (
            "query pipeline_id_by_code",
            "no project was selected",
            "pass --project",
            "Orchestration.Project",
            "the run's project",
        ):
            assert part in str(caught.value)
    finally:
        engine.dispose()


def test_project_zero_is_not_replaced_by_default():
    with selected_project(0):
        assert current_project_id() == 0


def test_an_explicit_project_id_needs_no_selection():
    from sqlalchemy.exc import OperationalError

    from etl_craft.engine.queries import statement

    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn, selected_project(None):
            query = statement(conn, "alert_channel")
            # Binding succeeds with the caller's project; only the missing table fails.
            with pytest.raises(OperationalError, match="no such table"):
                conn.execute(query, {"project_id": 2, "channel_name": "oncall"})
    finally:
        engine.dispose()
