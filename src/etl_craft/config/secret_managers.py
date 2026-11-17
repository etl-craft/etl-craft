"""Variables held in one AWS Secrets Manager secret or one Vault KV v2 path.

The secret is a JSON object (AWS) or a KV v2 entry (Vault) whose keys are the variable names
``craft-connector.yml`` refers to, like a ``.env`` file kept in a secret manager. It is read
once per ``Secrets.Cache_seconds`` per process; credentials come from the platform (the AWS
credential chain, or ``VAULT_TOKEN`` / ``~/.vault-token``), never from the configuration file.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from etl_craft.core.enums import SecretsSource
from etl_craft.core.errors import ConfigurationError

if TYPE_CHECKING:
    from etl_craft.config.model import SourceConfig

_CACHE: dict[tuple[str, str, str | None, str | None], tuple[float, dict[str, str]]] = {}
_LOCK = Lock()
TIMEOUT_SECONDS = 10


def managed_values(source: SourceConfig) -> dict[str, str]:
    """Return the secret's variables, fetching again once the cached copy is older than allowed."""
    key = (str(source.type), str(source.path), source.address, source.region)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
    values = _vault(source) if source.type == SecretsSource.VAULT else _aws(source)
    with _LOCK:
        _CACHE[key] = (now + source.cache_seconds, values)
    return values


def _where(source: SourceConfig) -> str:
    return f"Secrets.Source_type {source.type}, Secrets.Path {source.path!r}"


def _variables(source: SourceConfig, document: object) -> dict[str, str]:
    """Require a flat mapping of variable names to text, naming offending keys only."""
    if not isinstance(document, dict):
        raise ConfigurationError(
            f"{_where(source)}: the secret is not a JSON object; expected a mapping of variable "
            "names to values; store the variables as one key-value secret"
        )
    wrong = sorted(str(key) for key, value in document.items() if not isinstance(value, str))
    if wrong:
        raise ConfigurationError(
            f"{_where(source)}: keys {wrong} hold non-text values; expected every value to be "
            "a string; store each variable's value as text"
        )
    return dict(document)


def _aws(source: SourceConfig) -> dict[str, str]:
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        raise ConfigurationError(
            f"{_where(source)}: boto3 is not installed; expected the aws extra; "
            "install etl-craft[aws]"
        ) from None
    try:
        client = boto3.client("secretsmanager", region_name=source.region)
        answer = client.get_secret_value(SecretId=source.path)
    except (BotoCoreError, ClientError) as error:
        raise ConfigurationError(
            f"{_where(source)}: reading the secret failed ({type(error).__name__}: {error}); "
            "expected a readable secret; check the secret name, region and this host's AWS "
            "credentials (secretsmanager:GetSecretValue)"
        ) from None
    text = answer.get("SecretString")
    if text is None:
        raise ConfigurationError(
            f"{_where(source)}: the secret holds binary data; expected a JSON SecretString; "
            "store the variables as a key-value secret"
        )
    try:
        return _variables(source, json.loads(text))
    except json.JSONDecodeError:
        raise ConfigurationError(
            f"{_where(source)}: the secret is not JSON; expected a JSON object of variables; "
            "store the variables as a key-value secret"
        ) from None


def _vault_token() -> str:
    token = os.environ.get("VAULT_TOKEN", "").strip()
    if token:
        return token
    try:
        return (Path.home() / ".vault-token").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _vault(source: SourceConfig) -> dict[str, str]:
    token = _vault_token()
    if not token:
        raise ConfigurationError(
            f"{_where(source)}: no Vault token found; expected VAULT_TOKEN or ~/.vault-token; "
            "log in to Vault on this host or set VAULT_TOKEN"
        )
    mount, _, secret = str(source.path).partition("/")
    url = f"{str(source.address).rstrip('/')}/v1/{mount}/data/{secret}"
    request = urllib.request.Request(url, headers={"X-Vault-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            document = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise ConfigurationError(
            f"{_where(source)}: Vault answered HTTP {error.code} for {url}; expected a readable "
            "KV v2 entry; check the mount and path and the token's read policy"
        ) from None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"{_where(source)}: reading {url} failed ({type(error).__name__}); expected a "
            "reachable Vault server; check Secrets.Address or VAULT_ADDR and the network"
        ) from None
    data = document.get("data") if isinstance(document, dict) else None
    return _variables(source, data.get("data") if isinstance(data, dict) else None)
