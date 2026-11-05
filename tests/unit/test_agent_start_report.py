"""A failed parent START exchange still yields an observed process ending."""

import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from etl_craft.agent import loop
from etl_craft.agent.loop import AgentLoop, RunningTask
from etl_craft.core.enums import AttemptStatus, SlotKind
from etl_craft.core.errors import ServerError
from etl_craft.execution.processes import ChildSpec, run_child

pytestmark = pytest.mark.unit


def test_failed_start_report_stops_child_and_preserves_ending_evidence(tmp_path, monkeypatch):
    temporary = tempfile.TemporaryDirectory(dir=tmp_path)
    task = RunningTask(42, SlotKind.PYTHON, tmp_path, temporary, 1000)
    client = Mock()
    client.call.side_effect = ServerError("START response lost; restore the API")
    agent = SimpleNamespace(client=client)
    agent._report_started = lambda task, pid, birth: AgentLoop._report_started(
        agent, task, pid, birth
    )
    outcome = run_child(
        ChildSpec(
            (sys.executable, "-c", "import threading; threading.Event().wait()"),
            timeout_seconds=5,
            log_path=tmp_path / "output",
        ),
        cancel=task.cancel,
        on_started=lambda pid: AgentLoop._started(agent, task, pid),
    )
    assert outcome.cancelled
    assert outcome.pid is not None and outcome.process_start is not None
    assert outcome.returncode != 0
    assert task.forced_status == AttemptStatus.FAILED
    assert "42" in task.forced_message
    assert "START" in task.forced_message
    client.call.side_effect = None
    client.token = "test-agent"
    agent.config = Mock()
    monkeypatch.setattr(loop, "process_local_queries", lambda config: False)
    monkeypatch.setattr(loop, "confirm", lambda config, tag: None)
    assert AgentLoop._finish(agent, task, outcome)
    ending = client.call.call_args.args[1]
    start = client.call.call_args_list[-2].args[1]
    assert start.pid == outcome.pid and start.process_start == outcome.process_start
    assert task.started_reported
    assert ending.status == AttemptStatus.FAILED
    assert ending.pid == outcome.pid
    assert ending.process_start == outcome.process_start
    assert ending.queries_ended
    assert "START" in ending.error_message
    temporary.cleanup()
