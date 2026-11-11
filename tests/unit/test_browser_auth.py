"""The browser signing key remains an optional variable reference, never a config value."""

from pathlib import Path

import pytest

from etl_craft.config.loader_auth import parse_auth
from etl_craft.config.resolve import Resolver
from etl_craft.core.errors import ConfigurationError

pytestmark = pytest.mark.unit


def test_browser_secret_is_an_optional_unresolved_variable_reference():
    path = Path("craft-connector.yml")
    resolver = Resolver({"BROWSER_SECRET": "private-value"}, "test source", path)
    assert parse_auth({}, None, path, resolver).browser_state_secret is None
    config = parse_auth({"Auth": {"Browser_state_secret": "BROWSER_SECRET"}}, None, path, resolver)
    assert config.browser_state_secret == "BROWSER_SECRET"
    assert "private-value" not in repr(config)


@pytest.mark.parametrize("value", ["literal secret!", 32, {"secret": "value"}])
def test_browser_secret_refuses_values_that_are_not_variable_names(value):
    path = Path("craft-connector.yml")
    with pytest.raises(ConfigurationError, match=r"Browser_state_secret.*name of a variable"):
        parse_auth(
            {"Auth": {"Browser_state_secret": value}}, None, path, Resolver({}, "test", path)
        )
