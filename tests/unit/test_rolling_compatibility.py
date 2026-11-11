"""Peer versions and refusals use the installed compatibility knowledge."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from etl_craft import __version__
from etl_craft.config.loader_helpers import reject_unknown
from etl_craft.core.errors import ConfigurationError, RunRefusedError
from etl_craft.services.operations.agents import check_agent

pytestmark = pytest.mark.unit


def test_agent_accepts_same_major_patch_and_minor():
    major = __version__.split(".")[0]
    with pytest.raises(RunRefusedError, match="token identity is missing"):
        check_agent(
            SimpleNamespace(credential_token_id=None), SimpleNamespace(version=f"{major}.99.99")
        )


def test_unknown_setting_names_binary_input_and_upgrade():
    with pytest.raises(ConfigurationError) as caught:
        reject_unknown({"Future_setting": True}, frozenset(), "Auth", Path("craft-connector.yml"))
    for part in (__version__, "Auth.Future_setting", "upgrade", "supports"):
        assert part in str(caught.value)


@pytest.mark.parametrize("component", ["controller", "UI", "agent", "CLI"])
def test_peer_range_accepts_same_major_and_refuses_other_major(component):
    from etl_craft.core.compatibility import require_peer_version

    for peer in ("0.9.0", "0.10.0", "0.10.99"):
        require_peer_version("0.10.1", peer, component)
    with pytest.raises(ConfigurationError) as caught:
        require_peer_version("0.10.1", "1.0.0", component)
    for part in ("0.10.1", "1.0.0", ">=0.0.0,<1.0.0", "upgrade", component):
        assert part in str(caught.value)


def test_installed_registry_names_known_release_and_accepts_supported_input():

    reject_unknown(
        {"Browser_state_secret": "KEY"},
        {"Browser_state_secret"},
        "Auth",
        Path("craft-connector.yml"),
    )
    with pytest.raises(ConfigurationError) as caught:
        reject_unknown({"Browser_state_secret": "KEY"}, set(), "Auth", Path("craft-connector.yml"))
    for part in ("Auth.Browser_state_secret", "0.9.0", __version__, "upgrade"):
        assert part in str(caught.value)


def test_every_accepted_input_has_an_introduction_release():
    import argparse

    from etl_craft.cli import build_parser
    from etl_craft.config.loader import SECTIONS, settings_by_section
    from etl_craft.core.compatibility import INTRODUCED, InputKind
    from etl_craft.core.enums import Handler
    from etl_craft.engine.repository.config_rows import TABLES
    from etl_craft.engine.repository.pipelines import PIPELINE_PARAMETER_KINDS
    from etl_craft.handlers import python_scripts
    from etl_craft.handlers.parameters import known_parameters
    from etl_craft.handlers.registry import COMMON_PARAMETERS

    def options(parser):
        names = set(parser._option_string_actions)
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    names.update(options(child))
        return names

    inventories = {
        InputKind.SETTING: {
            f"{section}.{key}" for section, keys in settings_by_section().items() for key in keys
        }
        | set(SECTIONS),
        InputKind.COLUMN: {
            f"{table.file}.{column.name}" for table in TABLES for column in table.columns
        },
        InputKind.PARAMETER: set(PIPELINE_PARAMETER_KINDS)
        | set(python_scripts.PARAMETERS)
        | set(COMMON_PARAMETERS)
        | set().union(*(known_parameters(handler) or () for handler in Handler)),
        InputKind.CLI_OPTION: options(build_parser()),
    }
    for kind, names in inventories.items():
        assert not names - INTRODUCED[kind].keys(), (
            f"add introduction releases for {kind}: {names - INTRODUCED[kind].keys()}"
        )


def test_unknown_builtin_parameter_refused_before_execution():
    from etl_craft.core.errors import MetadataError
    from etl_craft.handlers.parameters import require_task_parameters

    with pytest.raises(MetadataError) as caught:
        require_task_parameters("SQL", {"FUTURE_PARAMETER": "yes"})
    for part in (__version__, "FUTURE_PARAMETER", "upgrade"):
        assert part in str(caught.value)
    require_task_parameters("SQL", {"SCRIPT_FILE": "input.sql"})
    require_task_parameters("PYTHON", {"MY_SCRIPT_ARGUMENT": "yes"})


@pytest.mark.parametrize("option", ["--future-option", "-z"])
def test_unknown_cli_option_names_binary_and_upgrade(capsys, option):
    from etl_craft.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args([option])
    message = capsys.readouterr().err
    for part in (__version__, option, "upgrade", "supports"):
        assert part in message


def test_unknown_csv_column_names_binary_input_and_upgrade(tmp_path):
    from etl_craft.core.errors import MetadataFileError
    from etl_craft.services.config_files import read_config_files

    (tmp_path / "pipelines.csv").write_text("PIPELINE_CODE,FUTURE_COLUMN\nEXAMPLE,yes\n")
    with pytest.raises(MetadataFileError) as caught:
        read_config_files(tmp_path)
    for part in (__version__, "pipelines.csv.FUTURE_COLUMN", "upgrade"):
        assert part in str(caught.value)


@pytest.mark.parametrize(
    "where,key", [("Engine.team", "Jdbc_url"), ("Object_stores.team", "Region")]
)
def test_profiled_known_setting_names_its_registered_release(where, key):
    with pytest.raises(ConfigurationError) as caught:
        reject_unknown({key: "value"}, set(), where, Path("craft-connector.yml"))
    for part in (__version__, "0.9.0", where, key, "upgrade"):
        assert part in str(caught.value)


def test_unknown_top_level_setting_names_binary_and_upgrade(tmp_path):
    from etl_craft.config import load_config

    path = tmp_path / "craft-connector.yml"
    path.write_text("Future_section: {}\n")
    with pytest.raises(ConfigurationError) as caught:
        load_config(path)
    for part in (__version__, "Future_section", "upgrade", "supports"):
        assert part in str(caught.value)
