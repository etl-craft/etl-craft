"""Initialize an isolated deployment smoke project from inside the UI image."""

import os
import subprocess
import sys
from pathlib import Path

from etl_craft.config import load_config
from etl_craft.core.actor import Actor, ActorKind
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.dialects.engine import build_engine
from etl_craft.services.operations import OperationContext
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.tokens import CreatedToken, TokenCreate

subprocess.run(
    ["etl-craft", "setup", "--admin-name", "smoke-admin", "--password-stdin"],
    input=os.environ["SMOKE_ADMIN_PASSWORD"] + "\n",
    text=True,
    stdout=sys.stderr,
    check=True,
)
config = load_config(Path("craft-connector.yml"))
engine = build_engine(config)
ctx = OperationContext(engine, config, Actor("smoke-admin", ActorKind.USER), role=ApiRole.ADMIN)
operator = invoke(ctx, ActionName.TOKEN_CREATE, TokenCreate(name="smoke-host", role=ApiRole.ADMIN))
agent = invoke(
    ctx,
    ActionName.TOKEN_CREATE,
    TokenCreate(name="smoke-agent", role=ApiRole.AGENT, pool="default"),
)
assert isinstance(operator, CreatedToken) and isinstance(agent, CreatedToken)
engine.dispose()
Path("python_scripts").mkdir(exist_ok=True)
Path("python_scripts/load.py").write_text(
    "from etl_craft.scripting import ScriptResult\n\ndef run(task):\n    return ScriptResult(7)\n",
    encoding="utf-8",
)
Path("migrations").mkdir(exist_ok=True)
Path("migrations/0001_smoke.sql").write_text(
    """
INSERT INTO CFG_PIPELINES (PROJECT_ID, PIPELINE_CODE, PIPELINE_NAME, REFRESH_TYPE)
SELECT PROJECT_ID, 'SMOKE', 'Deployment smoke', 'FULL' FROM ETL_CRAFT_PROJECT;

INSERT INTO CFG_TASKS (TASK_CODE, TASK_TYPE, PIPELINE_ID, HANDLER)
SELECT 'load', 'INGESTION', p.PIPELINE_ID, 'PYTHON' FROM CFG_PIPELINES p
JOIN ETL_CRAFT_PROJECT q ON q.PROJECT_ID=p.PROJECT_ID WHERE p.PIPELINE_CODE='SMOKE';

INSERT INTO CFG_TASK_PARAMETERS (TASK_ID, PARAMETER_NAME, PARAMETER_VALUE)
SELECT t.TASK_ID, params.name, params.value FROM CFG_TASKS t
JOIN CFG_PIPELINES p ON p.PIPELINE_ID=t.PIPELINE_ID
JOIN ETL_CRAFT_PROJECT q ON q.PROJECT_ID=p.PROJECT_ID
CROSS JOIN (VALUES ('SCRIPT_FILE', 'python_scripts/load.py'), ('SCRIPT_KIND', 'INGESTION'))
AS params(name, value) WHERE p.PIPELINE_CODE='SMOKE';
""",
    encoding="utf-8",
)
for command in (["migrate"], ["bundle", "publish"], ["pipelines", "refresh"]):
    subprocess.run(
        ["etl-craft", *command],
        env={**os.environ, "ETL_CRAFT_TOKEN": operator.token},
        stdout=sys.stderr,
        check=True,
    )
print(operator.token, agent.token, agent.metadata.token_id)
