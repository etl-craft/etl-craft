"""Private audit identities never preserve offline-guessable warehouse fingerprints."""

import hashlib
from dataclasses import replace

import pytest

from etl_craft.config import ConnectionProfile
from etl_craft.config.privacy import privacy_secret
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.privacy import PrivacyDomain, digest
from etl_craft.engine.privacy import checked
from fixtures.engine_db import engine_config

pytestmark = pytest.mark.unit


def test_private_domains_do_not_retain_md5_or_cross_match():
    value = hashlib.md5(b"V1:1").hexdigest()
    identities = {digest("private", domain, value) for domain in PrivacyDomain}
    assert len(identities) == len(PrivacyDomain)
    assert value not in identities
    assert all(len(identity) == 64 for identity in identities)
    assert digest("private", PrivacyDomain.KEY, value) == digest(
        "private", PrivacyDomain.KEY, value
    )


def test_privacy_secret_missing_and_changed_fail_with_project_and_remedy(monkeypatch):
    config = replace(
        engine_config(ConnectionProfile("ENGINE", "dev", "jdbc:sqlite:engine.db", "", "NONE")),
        project="private_project",
    )
    with pytest.raises(ConfigurationError) as missing:
        privacy_secret(config)
    assert "private_project" in str(missing.value)
    assert "Privacy.Hmac_secret" in str(missing.value)
    assert "configure" in str(missing.value)
    config = replace(config, privacy_hmac_secret="PROJECT_PRIVACY")
    monkeypatch.setenv("PROJECT_PRIVACY", "changed")
    with pytest.raises(ConfigurationError) as changed:
        checked(config, digest("original", PrivacyDomain.CHECK))
    for part in ("private_project", "differs", "restore the original secret"):
        assert part in str(changed.value)


def test_private_fingerprints_do_not_cross_targets_or_value_columns():
    from etl_craft.core.privacy import fingerprint

    value = hashlib.md5(b"V1:1").hexdigest()
    assert fingerprint("secret", PrivacyDomain.KEY, "people", value) != fingerprint(
        "secret", PrivacyDomain.KEY, "orders", value
    )
    assert fingerprint("secret", PrivacyDomain.VALUE, "people", value, "email") != fingerprint(
        "secret", PrivacyDomain.VALUE, "people", value, "note"
    )
