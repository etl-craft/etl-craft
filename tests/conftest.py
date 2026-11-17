"""Suite-wide pytest configuration: evidence, the suite-marker rule, Engine DB fixtures."""

import pytest

pytest_plugins = [
    "pytester",
    "plugins.evidence",
    "plugins.ci_shards",
    "plugins.suites",
    "plugins.demo_diagnostics",
    "fixtures.engine_db",
    "fixtures.retention",
    "fixtures.cli_project",
    "fixtures.cluster",
    "fixtures.pool_contract",
    "fixtures.metadata_project",
    "fixtures.sql_warehouse",
    "fixtures.smtp",
    "fixtures.oidc",
]


@pytest.fixture(autouse=True)
def forget_resolved_secrets():
    """Each test starts without secrets another test's process resolved and remembered."""
    from etl_craft.core import redaction

    yield
    redaction._RESOLVED.clear()
