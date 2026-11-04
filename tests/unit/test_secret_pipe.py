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
