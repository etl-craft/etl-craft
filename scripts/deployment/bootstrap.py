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
for command in (["migrate"], ["bundle", "publish"], ["pipelines", "refresh"]):
    subprocess.run(
        ["etl-craft", *command],
        env={**os.environ, "ETL_CRAFT_TOKEN": operator.token},
        stdout=sys.stderr,
        check=True,
    )
print(operator.token, agent.token, agent.metadata.token_id)
