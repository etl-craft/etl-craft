"""Column lineage shared by user operations and warehouse task handlers."""

from etl_craft.engine.project_scope import configured_project
from etl_craft.handlers.lineage import COPY as COPY
from etl_craft.handlers.lineage import SQLGLOT_VERSION as SQLGLOT_VERSION
from etl_craft.handlers.lineage import Edge as Edge
from etl_craft.handlers.lineage import LineageGraph as LineageGraph
from etl_craft.handlers.lineage import TaskLineage as TaskLineage
from etl_craft.handlers.lineage import cache_edge as cache_edge
from etl_craft.handlers.lineage import collect as handler_collect
from etl_craft.handlers.lineage import dialect_and_catalog as dialect_and_catalog
from etl_craft.handlers.lineage import extract as extract
from etl_craft.handlers.lineage import historical_lineage as historical_lineage
from etl_craft.handlers.lineage import lineage_key as lineage_key
from etl_craft.handlers.lineage import referenced_tables as referenced_tables
from etl_craft.handlers.lineage import script_lineage as script_lineage
from etl_craft.handlers.lineage import stored_edge as stored_edge
from etl_craft.handlers.lineage import table_name as table_name

collect = configured_project(handler_collect)
"""Collect lineage in the connector's project unless the caller already selected one."""
