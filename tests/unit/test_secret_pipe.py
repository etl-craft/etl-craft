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

    from etl_craft.execution.secret_pipe import capture_output

    chunks = iter([b"shared-prefix", b"-private-tail", b""])
    monkeypatch.setattr("os.read", lambda fd, size: next(chunks))
    monkeypatch.setattr("select.select", lambda *args: ([1], [], []))
    source = Mock()
    output = io.BytesIO()
    capture_output(
        source,
        output,
        ("shared-prefix", "shared-prefix-private-tail"),
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
