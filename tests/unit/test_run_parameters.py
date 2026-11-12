"""Run-input parsing is identical across interfaces and never silently loses duplicates."""

import pytest

from etl_craft.core.errors import UsageError

pytestmark = pytest.mark.unit


def test_run_parameter_values_preserve_equals_and_canonical_task_keys():
    from etl_craft.services.operations.run_parameters import parse

    assert parse(('load.INPUT_PARAMS={"source":"a=b"}',)) == {
        "load": {"INPUT_PARAMS": '{"source":"a=b"}'}
    }
    assert parse(()) == {}
    assert parse(("secret_loader.INPUT_PARAMS={}",)) == {"secret_loader": {"INPUT_PARAMS": "{}"}}


@pytest.mark.parametrize(
    "values,parts",
    [
        (("INPUT_PARAMS=1",), ("INPUT_PARAMS=1", "TASK.PARAM=VALUE", "correct")),
        (
            ("load.INPUT_PARAMS=1", "load.INPUT_PARAMS=2"),
            ("load.INPUT_PARAMS", "duplicate", "remove"),
        ),
        (("load.INPUT_PARAMS",), ("load.INPUT_PARAMS", "TASK.PARAM=VALUE", "correct")),
    ],
)
def test_run_parameter_refusals_explain_the_input_and_remedy(values, parts):
    from etl_craft.services.operations.run_parameters import parse

    with pytest.raises(UsageError) as caught:
        parse(values)
    for part in parts:
        assert part in str(caught.value)


def test_cli_retains_override_assignments_for_the_shared_operation():
    from etl_craft.cli import build_parser

    args = build_parser().parse_args(
        ["run", "--pipeline-code", "P", "--param", "load.INPUT_PARAMS={}", "--request-key", "one"]
    )
    assert args.params == ["load.INPUT_PARAMS={}"] and args.request_key == "one"


def test_credential_overrides_are_refused_without_auditing_or_echoing_the_value():
    from etl_craft.services.operations.requests import RunRequest, arguments
    from etl_craft.services.operations.run_parameters import parse

    request = RunRequest(pipeline_code="P", params=("load.SECRETS=private-value",))
    assert "private-value" not in str(arguments(request))
    with pytest.raises(UsageError) as caught:
        parse(request.params)
    assert "private-value" not in str(caught.value)
    assert "load.SECRETS" in str(caught.value) and "variable references" in str(caught.value)


def test_effective_definition_keeps_catalog_json_and_row_values_in_sync():
    import json

    from etl_craft.core.definitions import Definition
    from etl_craft.engine.run_overrides import effective

    original = Definition.read(
        json.dumps(
            {
                "_version": 2,
                "CFG_TASKS": {
                    "columns": ["task_id", "task_code", "pipeline_id"],
                    "rows": [{"task_id": 1, "task_code": "load", "pipeline_id": 1}],
                },
                "CFG_TASK_PARAMETERS": {
                    "columns": ["task_id", "parameter_name", "parameter_value"],
                    "rows": [
                        {"task_id": 1, "parameter_name": "INPUT_PARAMS", "parameter_value": "old"}
                    ],
                },
            }
        )
    )
    overlaid = effective(original, {"load": {"INPUT_PARAMS": "new"}}, 1)
    assert overlaid.rows["CFG_TASK_PARAMETERS"][0]["parameter_value"] == "new"
    assert json.loads(overlaid.text)["CFG_TASK_PARAMETERS"]["rows"][0]["parameter_value"] == "new"
    assert json.loads(original.text)["CFG_TASK_PARAMETERS"]["rows"][0]["parameter_value"] == "old"


@pytest.mark.parametrize(
    "params,changed,refused",
    [
        ({"SQL_ACTION": "APPEND_TABLE", "ALLOW_EMPTY": "false"}, {"ALLOW_EMPTY": "true"}, True),
        (
            {"SQL_ACTION": "APPEND_TABLE", "REJECT_LIMIT": "10", "SKIP_REJECTS_OVER_LIMIT": "true"},
            {"REJECT_LIMIT": ""},
            True,
        ),
        ({"SQL_ACTION": " append_table ", "REJECT_LIMIT": "10"}, {"REJECT_LIMIT": "20"}, False),
    ],
)
def test_override_validation_reuses_handler_applicability_and_cross_parameter_rules(
    params, changed, refused
):
    import json

    from etl_craft.core.definitions import Definition
    from etl_craft.services.operations.run_parameters import validate

    definition = Definition.read(
        json.dumps(
            {
                "_version": 2,
                "CFG_TASKS": {
                    "columns": ["task_id", "task_code", "handler", "active_flag", "pipeline_id"],
                    "rows": [
                        {
                            "task_id": 1,
                            "task_code": "load",
                            "handler": "SQL",
                            "pipeline_id": 1,
                            "active_flag": "Y",
                        }
                    ],
                },
                "CFG_TASK_PARAMETERS": {
                    "columns": ["task_id", "parameter_name", "parameter_value", "active_flag"],
                    "rows": [
                        {
                            "task_id": 1,
                            "parameter_name": name,
                            "parameter_value": value,
                            "active_flag": "Y",
                        }
                        for name, value in params.items()
                    ],
                },
            }
        )
    )
    if refused:
        with pytest.raises(UsageError):
            validate(definition, {"load": changed}, 1)
    else:
        validate(definition, {"load": changed}, 1)
