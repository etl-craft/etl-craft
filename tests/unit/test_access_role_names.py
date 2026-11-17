"""Role names remain exact printable identifiers across every interface."""

import pytest

from etl_craft.core.errors import UsageError
from etl_craft.services.operations.roles import RoleName

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", [" runner", "runner ", "a\tb", "a\nb"])
def test_role_names_refuse_whitespace_and_nonprintable_characters(name):
    with pytest.raises(UsageError, match="expected 1 to 64 characters without spaces"):
        RoleName(name=name)


@pytest.mark.parametrize(
    "field",
    ["project", "environment", "group", "account", "audience", "pipeline", "tag", "role", "action"],
)
def test_binding_selectors_refuse_explicit_blank_values(field):
    from etl_craft.services.operations.access_models import AccessWrite

    values = {"reason": "test", "project": "default", "account": "ana", "role": "runner", field: ""}
    with pytest.raises(UsageError, match=f"`{field}` must not be blank when given"):
        AccessWrite(**values)
