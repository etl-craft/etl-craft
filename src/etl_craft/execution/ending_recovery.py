"""Explicit, attributed recovery of missing terminal attempt evidence."""

from sqlalchemy.engine import Engine, Row

from etl_craft.config import ConnectorConfig
from etl_craft.core.enums import AgentStatus, AttemptStatus, EndingEvidenceKind
from etl_craft.core.errors import LockTimeoutError, RunRefusedError, UsageError
from etl_craft.core.ownership import attempt_holder
from etl_craft.core.time import as_utc
from etl_craft.engine import controls
from etl_craft.engine.queries import statement
from etl_craft.engine.resource_locks import holder_tag
from etl_craft.execution.control_flow import process_ended, process_local_queries
from etl_craft.warehouse.fencing import require_absent


def recover_endings(
    engine: Engine,
    config: ConnectorConfig,
    selection: tuple[int | None, int | None],
    *,
    attest_ended: bool = False,
    reason: str | None = None,
) -> tuple[int, ...]:
    """Verify first, then append evidence without changing outcomes or checkpoints."""
    with engine.connect() as conn:
        attempts = (
            conn.execute(
                statement(conn, "reconcile_ending_attempts"),
                dict(zip(("pipeline_id", "task_id"), selection, strict=True))
                | {"attest_ended": attest_ended},
            )
            .scalars()
            .all()
        )
    recovered = []
    for attempt_id in attempts:
        with engine.begin() as conn:
            row = conn.execute(
                statement(conn, "reconcile_ending_identity"), {"attempt_id": attempt_id}
            ).one()
            _fenced(row)
            if row.token_digest is not None:
                conn.execute(
                    statement(conn, "agent_registration_lock"), {"agent_id": int(row.owner_id)}
                ).all()
                row = conn.execute(
                    statement(conn, "reconcile_ending_identity"), {"attempt_id": attempt_id}
                ).one()
            _fenced(row)
            if not reason or not reason.strip():
                raise UsageError(
                    f"attempt {attempt_id}: ending evidence is missing; expected an operator "
                    "reason; rerun reconcile --reason REASON, adding --attest-ended only "
                    "when the original instance is gone"
                )
            observed = bool(row.process_observed) or process_ended(
                controls.affected(conn, (attempt_id,))[0]
            )
            checks: tuple[str, ...]
            if observed and process_local_queries(config):
                checks = ("lease_expired", "attempt_fenced", "process_exit", "embedded_query_exit")
            else:
                tag = holder_tag(attempt_holder(attempt_id, row.token_digest or row.owner_id))
                try:
                    require_absent(config, tag)
                except LockTimeoutError as error:
                    raise LockTimeoutError(f"attempt {attempt_id}: {error}") from error
                checks = ("lease_expired", "attempt_fenced", "tagged_queries_absent")
            evidence = EndingEvidenceKind.VERIFIED
            if not observed:
                if not attest_ended:
                    raise RunRefusedError(
                        f"attempt {attempt_id}: process ending cannot be verified "
                        f"on host {row.host}; "
                        "expected verified exit or explicit operator attestation; restore its "
                        "original agent or use reconcile --attest-ended --reason REASON"
                    )
                _instance_gone(row)
                evidence = EndingEvidenceKind.ATTESTED
                checks += ("original_instance_not_registered",)
            controls.observe_exit(
                conn,
                attempt_id,
                queries_ended=True,
                evidence=evidence,
                reason=reason,
                checks=checks,
            )
            recovered.append(attempt_id)
    return tuple(recovered)


def _fenced(row: Row[tuple[object, ...]]) -> None:
    if row.status in (AttemptStatus.CLAIMED, AttemptStatus.RUNNING, AttemptStatus.QUEUED) or (
        row.lease_expires_at is None or as_utc(row.lease_expires_at) >= as_utc(row.observed_now)
    ):
        raise RunRefusedError(
            f"attempt {row.attempt_id}: status={row.status}, lease={row.lease_expires_at}; "
            "expected an expired lease and terminal fence; stop/reconcile its owner before "
            "recording ending evidence"
        )


def _instance_gone(row: Row[tuple[object, ...]]) -> None:
    if row.registered_status in (None, AgentStatus.GONE):
        return
    if row.agent_instance_id is not None and row.registered_instance_id != row.agent_instance_id:
        return
    if (
        row.agent_instance_id is None
        and row.claimed_at is not None
        and (
            row.registered_at is not None
            and as_utc(row.registered_at) > as_utc(row.claimed_at)
            and row.registered_host != row.host
        )
    ):
        return
    raise RunRefusedError(
        f"attempt {row.attempt_id}: original instance {row.agent_instance_id or row.host} "
        "is still registered; expected its instance to be gone; drain and deregister the "
        "original agent before attesting, then supply the operator reason"
    )
