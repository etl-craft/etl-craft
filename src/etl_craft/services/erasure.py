"""Read-only erasure checks for validation and doctor."""

from typing import TYPE_CHECKING

from sqlalchemy.engine import Connection, Engine

from etl_craft.config import ConnectorConfig
from etl_craft.core.erasure import ErasureEntry
from etl_craft.core.errors import EtlCraftError
from etl_craft.core.redaction import registering
from etl_craft.engine.queries import statement
from etl_craft.handlers.erasure import apply_entries, check_column, secret
from etl_craft.handlers.resources import LocalLocker
from etl_craft.warehouse.connection import open_warehouse

if TYPE_CHECKING:
    from etl_craft.services.doctor import Check

Findings = tuple[list[str], list[str]]
"""Coverage failures, then erased tables whose old versions have no expiry bound."""


def problems(engine: Engine, config: ConnectorConfig, *, check_coverage: bool = True) -> list[str]:
    """Preflight active entries and report every lineage boundary without modifying data."""
    return findings(engine, config, check_coverage=check_coverage)[0]


def findings(engine: Engine, config: ConnectorConfig, *, check_coverage: bool = True) -> Findings:
    """Run one dry erasure pass for both the coverage failures and the retention warnings."""
    with engine.connect() as conn:
        entries = _registered(conn)
    return _checked(engine, config, entries, check_coverage)


def doctor_checks(engine: Engine, config: ConnectorConfig) -> list["Check"]:
    """Fail on coverage problems; warn on erased tables whose old versions never expire."""
    from etl_craft.services.doctor import fail, warn

    coverage, unbounded = findings(engine, config)
    return [fail("Erasure coverage", p) for p in coverage] + [
        warn("Erasure physical retention", p) for p in unbounded
    ]


def problems_on(
    conn: Connection, engine: Engine, config: ConnectorConfig, *, check_coverage: bool = True
) -> list[str]:
    """Check erasure entries in the caller's stable metadata transaction."""
    return _checked(engine, config, _registered(conn), check_coverage)[0]


def _registered(conn: Connection) -> tuple[ErasureEntry, ...]:
    return tuple(
        ErasureEntry(r.table_name, r.column_name, r.subject_key, r.key_hmac)
        for r in conn.execute(statement(conn, "erasure_entries"), {"all_entries": False})
    )


def _checked(
    engine: Engine,
    config: ConnectorConfig,
    entries: tuple[ErasureEntry, ...],
    check_coverage: bool,
) -> Findings:
    if not entries:
        return [], []
    try:
        with registering(*(entry.value for entry in entries)):
            return _problems(engine, config, entries, check_coverage)
    except EtlCraftError as error:
        return [str(error)], []


def _problems(
    engine: Engine,
    config: ConnectorConfig,
    entries: tuple[ErasureEntry, ...],
    check_coverage: bool,
) -> Findings:
    if not check_coverage:
        secret(config)
        with open_warehouse(config, LocalLocker(engine, config), hide_parameters=True) as warehouse:
            for entry in entries:
                check_column(warehouse, config, entry.table, entry.column)
        return [], []
    report = apply_entries(engine, config, entries, dry_run=True)
    found = [f"{b.table}: {b.reason} {b.remedy}" for b in report.unfollowed]
    unbounded = {
        t.table: (
            f"{t.table}: erased rows remain in {t.old_versions} with no bounded expiry; "
            f"expected a snapshot expiry bound for erased subjects. {t.retention}"
        )
        for t in report.tables
        if t.bounded is False
    }
    return found, list(unbounded.values())
