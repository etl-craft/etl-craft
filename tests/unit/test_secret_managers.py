"""Variables read from one AWS Secrets Manager secret or one Vault KV v2 entry, then cached."""

import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from etl_craft.config import load_config, resolve_secret, secret_managers
from etl_craft.core.errors import ConfigurationError

pytestmark = pytest.mark.unit

SECRET_VALUE = "manager-held-password-731"
ENGINE = """
Orchestration:

Engine:
  dev:
    Jdbc_url: jdbc:postgresql://localhost:5432/etl_craft
    Schema: public
    User: ENGINE_USER
    Auth_mode: PASSWORD
    Secret: ENGINE_SECRET
"""
VARIABLES = {"ENGINE_USER": "etl_engine", "ENGINE_SECRET": SECRET_VALUE}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(secret_managers, "_CACHE", {})
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home")


def write(tmp_path: Path, secrets: str) -> Path:
    path = tmp_path / "craft-connector.yml"
    path.write_text("Secrets:\n" + secrets + ENGINE, encoding="utf-8")
    return path


class Vault:
    """A local Vault KV v2 server that counts reads and checks the token."""

    def __init__(self, document, status=200):
        self.reads = 0
        vault = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                vault.reads += 1
                vault.path = self.path
                ok = self.headers.get("X-Vault-Token") == "vault-token"
                self.send_response(status if ok else 403)
                self.end_headers()
                self.wfile.write(json.dumps({"data": {"data": document}}).encode())

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.address = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def vault(monkeypatch):
    monkeypatch.setenv("VAULT_TOKEN", "vault-token")
    server = Vault(VARIABLES)
    yield server
    server.close()


def test_vault_entry_supplies_variables_and_is_reused_for_the_cache_period(tmp_path, vault):
    path = write(
        tmp_path,
        f"  Source_type: VAULT\n  Path: secret/etl-craft/dev\n  Address: {vault.address}\n"
        "  Cache_seconds: 600\n",
    )
    config = load_config(path)
    assert resolve_secret(config, config.engine) == SECRET_VALUE
    assert vault.path == "/v1/secret/data/etl-craft/dev"
    assert vault.reads == 1
    load_config(path)
    assert vault.reads == 1


def test_a_zero_cache_reads_the_vault_entry_every_time(tmp_path, vault):
    path = write(
        tmp_path,
        f"  Source_type: VAULT\n  Path: secret/app\n  Address: {vault.address}\n"
        "  Cache_seconds: 0\n",
    )
    config = load_config(path)
    resolve_secret(config, config.engine)
    assert vault.reads == 2


def test_vault_refusals_name_the_source_and_never_a_value(tmp_path, vault, monkeypatch):
    secrets = f"  Source_type: VAULT\n  Path: secret/app\n  Address: {vault.address}\n"
    monkeypatch.setenv("VAULT_TOKEN", "wrong-token")
    with pytest.raises(ConfigurationError, match=r"Vault answered HTTP 403.*read policy") as caught:
        load_config(write(tmp_path, secrets))
    assert "wrong-token" not in str(caught.value)
    monkeypatch.delenv("VAULT_TOKEN")
    with pytest.raises(ConfigurationError, match="no Vault token found"):
        load_config(write(tmp_path, secrets))


def test_vault_values_must_be_text(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_TOKEN", "vault-token")
    server = Vault({**VARIABLES, "PORT": 5432})
    try:
        path = write(
            tmp_path, f"  Source_type: VAULT\n  Path: secret/app\n  Address: {server.address}\n"
        )
        with pytest.raises(ConfigurationError, match=r"keys \['PORT'\] hold non-text values") as e:
            load_config(path)
        assert SECRET_VALUE not in str(e.value)
    finally:
        server.close()


@pytest.mark.parametrize(
    ("secrets", "message"),
    [
        (
            "  Source_type: VAULT\n  Path: secret/app\n  Address: http://vault.internal:8200\n",
            r"expected https:// \(plain http only to localhost\)",
        ),
        ("  Source_type: VAULT\n  Path: secret/app\n", "no Vault address"),
        ("  Source_type: VAULT\n  Path: app\n  Address: https://v\n", "expected the KV v2 mount"),
        ("  Source_type: VAULT\n  Address: https://v\n", "Secrets.Path is required"),
        (
            "  Source_type: VAULT\n  Path: secret/app\n  Address: https://v\n  Cache_seconds: -1\n",
            "expected whole seconds from 0 to 86400",
        ),
        (
            "  Source_type: VAULT\n  Path: secret/app\n  Address: https://v\n  Region: eu-west-1\n",
            "Secrets.Region is only used with Source_type: AWS_SECRETS_MANAGER",
        ),
        (
            "  Source_type: AWS_SECRETS_MANAGER\n  Path: etl\n  Address: https://v\n",
            "Secrets.Address is only used with Source_type: VAULT",
        ),
        (
            "  Source_type: ENVIRONMENT\n  Cache_seconds: 60\n",
            "Secrets.Cache_seconds is only used with a secret manager",
        ),
    ],
)
def test_manager_settings_are_refused_with_their_remedy(tmp_path, secrets, message):
    with pytest.raises(ConfigurationError, match=message):
        load_config(write(tmp_path, secrets))


def fake_boto3(monkeypatch, answer=None, error=None):
    calls = []

    class ClientError(Exception):
        pass

    class Client:
        def get_secret_value(self, SecretId):  # noqa: N803 - the boto3 keyword
            calls.append(SecretId)
            if error:
                raise ClientError(error)
            return answer

    boto3 = types.SimpleNamespace(
        client=lambda service, region_name: calls.append((service, region_name)) or Client()
    )
    exceptions = types.SimpleNamespace(BotoCoreError=ClientError, ClientError=ClientError)
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", types.SimpleNamespace(exceptions=exceptions))
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exceptions)
    return calls


def test_aws_secret_supplies_variables_from_its_json_object(tmp_path, monkeypatch):
    calls = fake_boto3(monkeypatch, {"SecretString": json.dumps(VARIABLES)})
    path = write(
        tmp_path, "  Source_type: AWS_SECRETS_MANAGER\n  Path: etl-craft/dev\n  Region: eu-west-1\n"
    )
    config = load_config(path)
    assert resolve_secret(config, config.engine) == SECRET_VALUE
    assert calls == [("secretsmanager", "eu-west-1"), "etl-craft/dev"]


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        ({"SecretBinary": b"x"}, None, "holds binary data"),
        ({"SecretString": "not json"}, None, "the secret is not JSON"),
        ({"SecretString": "[1]"}, None, "not a JSON object"),
        (None, "AccessDenied", r"secretsmanager:GetSecretValue"),
    ],
)
def test_aws_refusals_name_the_secret_and_remedy(tmp_path, monkeypatch, answer, error, message):
    fake_boto3(monkeypatch, answer, error)
    path = write(tmp_path, "  Source_type: AWS_SECRETS_MANAGER\n  Path: etl-craft/dev\n")
    with pytest.raises(ConfigurationError, match=message) as caught:
        load_config(path)
    assert "Secrets.Path 'etl-craft/dev'" in str(caught.value)
