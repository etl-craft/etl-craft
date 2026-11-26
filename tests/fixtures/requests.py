"""Serve test calls inside a recorded request, as the CLI and API serve every action."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine

from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.engine.audit import command_request, register_engine


@contextmanager
def recorded_request(engine: Engine, command: str) -> Iterator[None]:
    """Record ``command`` in ``engine``'s AUD_ACTIONS for the duration of the block."""
    with acting_as(SYSTEM_ACTOR), command_request(command, {}, project_id=1):
        register_engine(engine)
        yield
