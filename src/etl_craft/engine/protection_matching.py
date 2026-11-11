"""Fenced host-only candidate matching for pending atomic deletions."""

import json

from sqlalchemy.engine import Connection

from etl_craft.config import ConnectorConfig
from etl_craft.core.enums_protection import ProtectionEvidence, ProtectionKind, ProtectionStatus
from etl_craft.core.errors import PermissionDeniedError
from etl_craft.core.privacy import PrivacyDomain, fingerprint
from etl_craft.core.protection import (
    MAX_PROTECTION_EVENTS,
    ProtectionCandidates,
    ProtectionMatches,
    ProtectionReport,
)
from etl_craft.engine.protection_events import Creator, fenced_access, recovery_owner
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.pipelines import current_project_id


def match(
    conn: Connection,
    config: ConnectorConfig,
    target: str,
    fencing: dict[str, object],
    candidates: ProtectionCandidates,
) -> ProtectionMatches:
    """Use the common live lock fence, terminal creator rule and domain-separated identities."""
    candidates.__post_init__()
    _page, key = fenced_access(conn, target, fencing, config=config)
    scope = {
        "project_id": current_project_id(),
        "target": target,
        "request_id": candidates.request_id,
    }
    creator = conn.execute(statement(conn, "protection_request"), scope).first()
    if (
        creator is None
        or creator.final_status is not None
        or creator.kind
        not in {
            ProtectionKind.HARD_DELETE,
            ProtectionKind.ERASURE,
        }
    ):
        raise PermissionDeniedError(
            f"request {candidates.request_id}, target {target}: expected a PENDING HARD_DELETE "
            "or ERASURE request; read pending intents before matching"
        )
    attempt = fencing["attempt_id"]
    assert attempt is None or isinstance(attempt, int)
    recovery_owner(
        target,
        candidates.request_id,
        Creator(creator.attempt_id, ProtectionKind(creator.kind), creator.attempt_status),
        ProtectionReport(
            ProtectionStatus.COMMITTED,
            request_id=candidates.request_id,
            evidence=ProtectionEvidence.KEYS_ABSENT,
        ),
        attempt,
        require_terminal=True,
    )
    assert key is not None
    hashed = {fingerprint(key, PrivacyDomain.KEY, target, value) for value in candidates.hashes}
    rows = conn.execute(
        statement(conn, "protection_candidate_page"),
        {
            **scope,
            "cursor": candidates.cursor,
            "page_size": MAX_PROTECTION_EVENTS + 1,
            "key_hashes": json.dumps(sorted(hashed)),
        },
    ).all()
    page = rows[:MAX_PROTECTION_EVENTS]
    matches = tuple(
        r.event_id
        for r in page
        if tuple(json.loads(r.column_names)) == candidates.columns and r.key_hash in hashed
    )
    return ProtectionMatches(
        matches,
        page[-1].event_id if len(rows) > MAX_PROTECTION_EVENTS else None,
    )
