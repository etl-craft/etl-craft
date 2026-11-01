"""A connection's initialization queries cannot stand in for the intended slow write."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fixtures import lock_fencing

pytestmark = pytest.mark.unit


def test_connection_initialization_cannot_acknowledge_a_running_write(monkeypatch):
    engine = MagicMock()
    engine.begin.return_value.__enter__.side_effect = OSError("connection unavailable")
    dialect = MagicMock()
    dialect.running_tagged.return_value = 1
    monkeypatch.setattr(lock_fencing, "build_warehouse_engine", lambda *a, **k: engine)
    monkeypatch.setattr(lock_fencing, "warehouse_dialect", lambda config: dialect)
    world = SimpleNamespace(config=None, warehouse=engine)
    with pytest.raises(AssertionError, match="connection never opened"):
        lock_fencing.start_old_write(world, "slow write", wait_seconds=0)
    dialect.running_tagged.assert_not_called()
