"""A task's credentials travel by stdin and never reach captured output."""

import json
import sys

import pytest

from etl_craft.execution.processes import ChildSpec, run_child

pytestmark = pytest.mark.unit


def test_pipe_input_and_split_output_are_masked(tmp_path):
    secret = "opaque-task-value"
    script = (
        "import json,os,sys\n"
        "value=json.load(sys.stdin)['TOKEN']\n"
        "assert 'TOKEN' not in os.environ\n"
        "assert value not in repr(sys.argv)\n"
        "os.write(1,b'x'*16380+value[:7].encode())\n"
        "os.write(1,value[7:].encode()+b'\\n')\n"
        "raise RuntimeError(value)\n"
    )
    path = tmp_path / "attempt.log"
    result = run_child(
        ChildSpec(
            (sys.executable, "-c", script),
            log_path=path,
            input_data=json.dumps({"TOKEN": secret}).encode(),
            redacted_values=(secret,),
        )
    )
    assert not result.succeeded
    assert secret not in path.read_text()
    assert secret not in result.output_tail
    assert "[REDACTED]" in result.output_tail
    assert secret not in repr(result.spec)


@pytest.mark.parametrize(
    "data",
    ['{"TOKEN": 12}', "private-not-json", "x" * (1024 * 1024 + 1)],
    ids=["nonstring", "invalid-json", "oversize"],
)
def test_invalid_pipe_payload_never_echoes_input(data):
    import io

    from etl_craft.core.errors import PermanentError
    from etl_craft.execution.secret_pipe import read_values

    with pytest.raises(PermanentError, match=r"credential pipe.*1 MiB.*restore") as error:
        read_values(io.StringIO(data))
    assert data[:20] not in str(error.value)


def test_overlapping_secret_prefix_waits_for_the_longer_value(monkeypatch):
    import io
    import threading
    from unittest.mock import Mock

    from etl_craft.execution.log_positions import LogPositions
    from etl_craft.execution.secret_pipe import RedactedOutput, capture_output

    chunks = iter([b"shared-prefix", b"-private-tail", b""])
    monkeypatch.setattr("os.read", lambda fd, size: next(chunks))
    monkeypatch.setattr("select.select", lambda *args: ([1], [], []))
    source = Mock()
    output = io.BytesIO()
    capture_output(
        source,
        RedactedOutput(LogPositions(output), ("shared-prefix", "shared-prefix-private-tail"), None),
        threading.Event(),
        [],
        threading.Event(),
    )
    assert output.getvalue() == b"[REDACTED]"


def test_unread_credential_pipe_does_not_block_task_timeout(monkeypatch):
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    children = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr("etl_craft.execution.processes.subprocess.Popen", launch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_child,
            ChildSpec(
                (sys.executable, "-c", "import threading; threading.Event().wait()"),
                timeout_seconds=0.1,
                input_data=b"x" * (1024 * 1024),
                redacted_values=("private",),
            ),
        )
        try:
            result = future.result(timeout=3)
            assert result.timed_out
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()


def test_claim_provider_is_a_closed_name():
    from etl_craft.agent.loop import Work
    from etl_craft.core.enums import SecretsSource
    from etl_craft.core.errors import ServerError
    from etl_craft.services.operations.serialization import from_json

    claim = {
        "task": {},
        "lease_seconds": 60,
        "timeout_seconds": 30,
        "credential": "scoped",
        "holder_id": "holder",
        "secret_provider": "FILE",
    }
    work = from_json(Work, claim)
    assert work.secret_provider is SecretsSource.FILE
    with pytest.raises(ServerError, match="secret_provider"):
        from_json(Work, claim | {"secret_provider": "not-a-provider"})


def test_error_marker_sequence_survives_secret_redaction():
    from io import BytesIO

    from etl_craft.core.error_anchors import ErrorPosition
    from etl_craft.execution.log_positions import LogPositions
    from etl_craft.execution.secret_pipe import RedactedOutput

    output = BytesIO(b"setup\n")
    positions = LogPositions(output)
    capture = RedactedOutput(positions, ("1", "hidden\nvalue"), "nonce")
    capture.write(b"hidden\n")
    capture.write(b"value\nerror: non")
    capture.write(b"ce[event 1] secret 1\n", final=True)
    assert output.getvalue() == b"setup\n[REDACTED]\nerror: [event 1] secret [REDACTED]\n"
    assert positions.first == positions.last == ErrorPosition(1, 17, 3)


def test_tracked_log_flushes_short_live_output_without_waiting_for_a_marker():
    from io import BytesIO

    from etl_craft.execution.log_positions import LogPositions
    from etl_craft.execution.secret_pipe import RedactedOutput

    output = BytesIO()
    capture = RedactedOutput(LogPositions(output), (), "nonce")
    capture.write(b"ready\n")
    assert output.getvalue() == b"ready\n"
    capture.write(b"error: no")
    capture.write(b"nce[event 1] detail\n")
    assert output.getvalue() == b"ready\nerror: [event 1] detail\n"
