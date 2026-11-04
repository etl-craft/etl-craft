"""Atomic landing and actual process loss on both cloud warehouses."""

import os

import pytest

from acceptance.cloud.test_cloud_sql_actions import close_world, cloud_world
from etl_craft.core.enums import TableFormat
from fixtures.cloud import DATABRICKS_VARS, SNOWFLAKE_VARS, require_variables
from fixtures.landing_crashes import check_landing_exit, check_landing_inflight

pytestmark = [pytest.mark.timeout(900), pytest.mark.usefixtures("engine_actor")]


@pytest.mark.parametrize(
    "vendor,variables",
    [
        pytest.param("Snowflake", SNOWFLAKE_VARS, marks=pytest.mark.cloud_snowflake),
        pytest.param("Databricks", DATABRICKS_VARS, marks=pytest.mark.cloud_databricks),
    ],
)
@pytest.mark.parametrize(
    "point", ["landing.before_publish", "landing.before_commit", "landing.after_commit", "inflight"]
)
def test_cloud_landing_crash_and_retry(tmp_path, monkeypatch, vendor, variables, point):
    prefix = vendor.upper()
    require_variables(prefix, variables)
    fields = {name.lower(): f"ETL_CRAFT_TEST_{prefix}_{name}" for name in variables}
    schema = os.environ[f"ETL_CRAFT_TEST_{prefix}_SCHEMA"]
    w = cloud_world(tmp_path, vendor, fields, TableFormat.NATIVE, schema, isolated=True)
    w.kind = prefix.lower()
    try:
        if point == "inflight":
            check_landing_inflight(w, monkeypatch)
        else:
            check_landing_exit(w, monkeypatch, point)
    finally:
        close_world(w)
