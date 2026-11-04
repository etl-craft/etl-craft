"""Upload provenance survives staging with or without declared account columns."""

import os

import pytest

from acceptance.cloud.test_cloud_sql_actions import close_world, cloud_world
from etl_craft.core.enums import TableFormat
from fixtures.cloud import DATABRICKS_VARS, SNOWFLAKE_VARS, require_variables
from fixtures.seed_columns import check_omitted_seed_columns
from integration.warehouse.test_upload_attribution import (
    test_ordinary_upload_rows_retain_ids_and_stamp_declared_actors as check_staging,
)
from integration.warehouse.test_upload_attribution import (
    test_two_uploads_retain_identity_until_their_merges_stamp_ods as check_chain,
)

pytestmark = [pytest.mark.timeout(1200), pytest.mark.usefixtures("engine_actor")]


@pytest.mark.parametrize(
    "vendor,variables",
    [
        pytest.param("Snowflake", SNOWFLAKE_VARS, marks=pytest.mark.cloud_snowflake),
        pytest.param("Databricks", DATABRICKS_VARS, marks=pytest.mark.cloud_databricks),
    ],
)
def test_cloud_upload_staging_and_ods(tmp_path, vendor, variables):
    prefix = vendor.upper()
    require_variables(prefix, variables)
    fields = {name.lower(): f"ETL_CRAFT_TEST_{prefix}_{name}" for name in variables}
    schema = os.environ[f"ETL_CRAFT_TEST_{prefix}_SCHEMA"]
    w = cloud_world(tmp_path, vendor, fields, TableFormat.NATIVE, schema, isolated=True)
    try:
        for action in ("APPEND_TABLE", "OVERWRITE_TABLE"):
            for declared in (True, False):
                check_staging(w, action, declared)
        check_chain(w)
        check_omitted_seed_columns(w, tmp_path / "seed")
    finally:
        close_world(w)
