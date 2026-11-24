"""Remote deadlines distinguish a sent request from an unavailable server."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from etl_craft.cli import client
from etl_craft.core.enums import ActionName
from etl_craft.core.erasure import ErasureReport
from etl_craft.core.errors import EtlCraftError, ExitCode, ServerError
from etl_craft.services.operations.deploy import DeployInput, Deployment
from etl_craft.services.operations.erasure import EraseInput
from etl_craft.services.operations.requests import NoInput
from fixtures.tls import localhost_tls

pytestmark = pytest.mark.unit
DEADLINE = 0.1


@pytest.fixture
def delayed_api(monkeypatch, request, tmp_path):
    arrived, reply = Event(), Event()
    delayed = getattr(request, "param", "headers")
    monkeypatch.setenv("ETL_CRAFT_TOKEN", "test-token")
    monkeypatch.setattr(client, "READ_TIMEOUT", DEADLINE, raising=False)
    open_request = client.open_request

    def open_with_short_deadline(request, timeout):
        # Exercise the old single deadline too, without waiting sixty seconds.
        if isinstance(timeout, (int, float)):
            timeout = DEADLINE
        return open_request(request, timeout)

    monkeypatch.setattr(client, "open_request", open_with_short_deadline)

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if delayed == "https-body":
                self.send_response(200)
                self.end_headers()
                self.wfile.flush()
                arrived.set()
                reply.wait(5)
            else:
                arrived.set()
                if not reply.wait(5):
                    return
                self.send_response(200)
                self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(
                    b'{"tables":[],"unfollowed":[],"dry_run":true}'
                    if self.path.endswith("/erasure")
                    else b'{"plan":true,"bundle_id":null,"config":null}'
                )

        def do_POST(self):
            self.respond()

        def do_GET(self):
            self.respond()

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        if delayed == "https-body":
            tls, certificate = localhost_tls(tmp_path)
            monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            url = f"https://localhost:{server.server_port}"
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        try:
            yield (
                client.ApiClient(url, "default"),
                arrived,
                reply,
            )
        finally:
            reply.set()
            server.shutdown()
            thread.join()


@pytest.mark.parametrize(
    ("name", "request_body", "expected"),
    [
        (
            ActionName.DEPLOY,
            DeployInput(plan=True),
            Deployment(plan=True, bundle_id=None, config=None),
        ),
        (
            ActionName.ERASE,
            EraseInput(table="customers", column="id", value="test", reason="test", dry_run=True),
            ErasureReport(dry_run=True),
        ),
    ],
)
def test_long_action_waits_for_the_server(delayed_api, name, request_body, expected):
    api, arrived, reply = delayed_api
    with ThreadPoolExecutor() as workers:
        result = workers.submit(api.invoke, name, request_body)
        try:
            assert arrived.wait(5)
            with pytest.raises(TimeoutError):
                result.exception(timeout=3 * DEADLINE)
        finally:
            reply.set()
        assert result.result(timeout=5) == expected


@pytest.mark.parametrize("delayed_api", ["headers", "https-body"], indirect=True)
def test_timeout_reports_the_sent_action_and_unknown_outcome(delayed_api):
    api, arrived, _ = delayed_api
    with pytest.raises(EtlCraftError) as error:
        api.invoke(ActionName.HEALTH, NoInput())
    assert arrived.is_set()
    assert error.value.exit_code == 33
    for part in (api.url, "health", "0.1", "may still be completing", "audit"):
        assert part in str(error.value)


def test_long_action_retains_the_connection_timeout(monkeypatch):
    monkeypatch.setenv("ETL_CRAFT_TOKEN", "test-token")

    def stalled(connection):
        assert connection.timeout == client.CONNECT_TIMEOUT
        raise TimeoutError("connect timed out")

    monkeypatch.setattr(HTTPConnection, "connect", stalled)
    api = client.ApiClient("http://127.0.0.1:9", "default")
    with pytest.raises(ServerError, match="connect timed out") as error:
        api.invoke(ActionName.DEPLOY, DeployInput(plan=True))
    assert error.value.exit_code is ExitCode.SERVER
