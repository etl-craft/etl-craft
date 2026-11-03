"""Check the immutable project key before using private audit identities."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from etl_craft.config import ConnectorConfig
from etl_craft.config.privacy import privacy_secret
from etl_craft.core.errors import ConfigurationError
from etl_craft.core.privacy import PrivacyDomain, digest
from etl_craft.engine.queries import statement


def checked(config: ConnectorConfig, stored: str | None, *, required: bool = False) -> str | None:
    """Resolve on the host and refuse rotation before exposing or mutating history."""
    if stored is None and not required:
        return None
    key = privacy_secret(config)
    if stored is not None and stored != digest(key, PrivacyDomain.CHECK):
        raise _changed(config)
    return key


def check(conn: Connection, config: ConnectorConfig, *, required: bool = True) -> str | None:
    """Share the project history check between erasure, validation and diagnostics."""
    stored = conn.execute(statement(conn, "privacy_check")).scalar_one_or_none()
    return checked(config, stored, required=required)


def problems(conn: Connection, config: ConnectorConfig) -> list[str]:
    """Report the same missing/changed secret to validation and doctor before runtime."""
    from etl_craft.core.errors import EtlCraftError

    try:
        needed = bool(conn.execute(statement(conn, "privacy_required")).scalar_one())
        check(conn, config, required=needed)
        return []
    except EtlCraftError as error:
        return [str(error)]


def _changed(config: ConnectorConfig) -> ConfigurationError:
    return ConfigurationError(
        f"project {config.project}: Privacy.Hmac_secret differs from the secret its history "
        "uses; expected the original secret; restore the original secret before protection "
        "or erasure writes, doctor or provenance reads; rotation is not supported"
    )


@contextmanager
def guarded(config: ConnectorConfig) -> Iterator[None]:
    """Translate a concurrent first-use key conflict without adding an append round trip."""
    try:
        yield
    except SQLAlchemyError as error:
        if "Privacy.Hmac_secret differs from project history" in str(getattr(error, "orig", error)):
            raise _changed(config) from None
        raise
