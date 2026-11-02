"""Deletion intents share the same event log and absent-key recovery as erasure."""

from collections.abc import Mapping

from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.protection import ProtectionEvent
from etl_craft.handlers.protection_recovery import pending
from etl_craft.handlers.sql.session import Session


def intent(
    session: Session,
    keys: tuple[str, ...],
    kind: ProtectionKind,
    selection: str,
    params: Mapping[str, object] | None = None,
) -> str | None:
    """Fingerprint exactly the keys selected for deletion, never their raw values."""
    store = session.protection_store
    assert store is not None
    rows = session.run(selection, params, step="fingerprint keys before deletion").scalars()
    return pending(
        store,
        session.target,
        (ProtectionEvent(kind, str(key), keys, (None,) * len(keys)) for key in rows),
        session.protection_requests,
    )
