"""A served etl-craft UI over HTTPS, with an admin and a viewer account, for browser tests."""

import base64
import hashlib
import socket
import subprocess
import threading
from dataclasses import replace

import pytest
import uvicorn

from etl_craft.api.app import create_app
from etl_craft.cli.console import console
from etl_craft.core.actor import SYSTEM_ACTOR, Actor, ActorKind, acting_as
from etl_craft.core.enums import ActionName, ApiRole
from etl_craft.engine.schema import init_db
from etl_craft.services.operations import OperationContext
from fixtures.actions import act
from fixtures.engine_db import sqlite_engine_db

PASSWORD = "correct horse battery"


@pytest.fixture(scope="session", autouse=True)
def browser_tls(tmp_path_factory):
    folder = tmp_path_factory.mktemp("browser-tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    public_key = subprocess.check_output(["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"])
    der = subprocess.check_output(
        ["openssl", "pkey", "-pubin", "-outform", "DER"], input=public_key
    )
    pin = base64.b64encode(hashlib.sha256(der).digest()).decode()
    with pytest.MonkeyPatch.context() as env:
        env.setenv("ETL_CRAFT_TEST_BROWSER_SPKI", pin)
        yield cert, key


@pytest.fixture
def site(tmp_path, request, browser_tls):
    cert, key = browser_tls
    db = sqlite_engine_db(tmp_path)
    with acting_as(SYSTEM_ACTOR):
        init_db(db.engine)
    config = db.config
    if getattr(request, "param", None) == "sso":
        config = replace(
            config,
            auth=replace(
                config.auth, oidc_issuer="https://issuer.example", oidc_client_id="console"
            ),
        )
    ctx = OperationContext(db.engine, config, Actor("owner", ActorKind.USER), role=ApiRole.ADMIN)
    act(ctx, ActionName.ACCOUNT_ADD, name="owner", role=ApiRole.ADMIN, password=PASSWORD)
    act(ctx, ActionName.ACCOUNT_ADD, name="alice", role=ApiRole.VIEWER, password=PASSWORD)
    ready = threading.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    if getattr(request, "param", None) == "sso-browser":
        from types import SimpleNamespace

        from etl_craft.config.model import DocsSiteConfig

        auth, _ = request.getfixturevalue("issuer")
        request.getfixturevalue("monkeypatch").setenv(
            "BROWSER_TEST_SECRET", "browser-test-key-material-of-at-least-thirty-two-bytes"
        )
        ctx = replace(
            ctx,
            config=replace(
                config,
                auth=SimpleNamespace(
                    **(vars(auth) | {"browser_state_secret": "BROWSER_TEST_SECRET"})
                ),
                docs_site=DocsSiteConfig(external_url=f"https://localhost:{port}"),
            ),
        )
    server = Server(
        uvicorn.Config(
            create_app(ctx, console=console()),
            ssl_keyfile=str(key),
            ssl_certfile=str(cert),
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    assert ready.wait(10)
    try:
        yield ctx, f"https://localhost:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
        assert not thread.is_alive()
        listener.close()
        db.engine.dispose()
