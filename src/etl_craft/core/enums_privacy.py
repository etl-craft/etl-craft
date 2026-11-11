"""Closed cryptographic domains for project privacy history."""

from enum import StrEnum


class PrivacyDomain(StrEnum):
    """Separate identities even when their inputs happen to be equal."""

    KEY = "etl-craft/protection-key/v1"
    VALUE = "etl-craft/protection-value/v1"
    ERASURE = "etl-craft/erasure-key/v1"
    CHECK = "etl-craft/privacy-key-check/v1"
