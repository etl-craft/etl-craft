"""A real HTTPS webhook receiver that can refuse or redirect deliveries."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fixtures.tls import localhost_tls


@pytest.fixture
def webhook(tmp_path, monkeypatch):
    context, certificate = localhost_tls(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    received = []
    state = {"status": 204, "body": b"receiver response must never be retained"}

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, body, dict(self.headers)))
            self.send_response(state["status"])
            if state["status"] == 302:
                self.send_header("Location", address + "/forwarded")
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("localhost", 0), Receiver)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    address = f"https://localhost:{server.server_port}"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield address, received, state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)
