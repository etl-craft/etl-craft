"""Upload-required validation fails permanently before invoking team code."""

from unittest.mock import Mock

import pytest

from etl_craft.config import parse_config
from etl_craft.core.errors import PermanentError
from etl_craft.handlers.file_validation import run
from etl_craft.handlers.registry import TaskContext

pytestmark = pytest.mark.unit


def test_required_upload_names_the_task_and_remedy_and_keeps_default_empty_behavior(tmp_path):
    folder = tmp_path / "validation_scripts"
    folder.mkdir()
    (folder / "check.py").write_text(
        'def validate(task):\n    raise AssertionError("must not run")\n'
    )
    config = parse_config(
        {
            "Secrets": {"Source_type": "ENVIRONMENT"},
            "Orchestration": {},
            "Engine": {"dev": {"Jdbc_url": "jdbc:sqlite:engine.db", "Schema": "main"}},
        },
        tmp_path / "craft-connector.yml",
    )
    params = {
        "SCRIPT_FILE": "validation_scripts/check.py",
        "FILE_FORMAT": "CSV",
        "REQUIRE_UPLOADS": "Y",
    }
    context = TaskContext(
        config,
        1,
        "SI_STEWARD_DS_AGENTS",
        1,
        "validate_file",
        1,
        1,
        1,
        "FILE_VALIDATION",
        "INCREMENTAL",
        params,
    )
    store = Mock()
    store.upload_files.return_value = ()
    with pytest.raises(PermanentError) as caught:
        run(context, store)
    for part in [
        "SI_STEWARD_DS_AGENTS",
        "validate_file",
        "no uploaded files in this run",
        "start the run from an upload in the UI",
        "etl-craft upload",
    ]:
        assert part in str(caught.value)
    store.validation_result.assert_not_called()
    params["REQUIRE_UPLOADS"] = "N"
    assert run(context, store).target_count == 0
    params.pop("REQUIRE_UPLOADS")
    assert run(context, store).target_count == 0
