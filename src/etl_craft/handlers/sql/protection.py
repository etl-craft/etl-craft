"""Row-local locks and value attribution, with hash-only write-ahead intents."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy.engine import RowMapping

from etl_craft.core.enums import ActorKind, SqlAction
from etl_craft.core.enums_protection import ProtectionKind
from etl_craft.core.errors import SqlGuardError
from etl_craft.core.protection import MAX_PROTECTION_COLUMNS, ProtectionEvent
from etl_craft.core.protection_state import ProtectionRequest as ProtectionRequest
from etl_craft.core.protection_state import RowProtection
from etl_craft.core.text import sha256_hex
from etl_craft.dialects.warehouse.merges import matched_merge
from etl_craft.dialects.warehouse.protection import ProtectionSql, bound_relation
from etl_craft.handlers.sql.protection_columns import (
    business_columns,
    contract,
    fingerprint,
    type_problems,
)
from etl_craft.handlers.sql.session import Session
from etl_craft.handlers.sql.spec import SqlTask
from etl_craft.handlers.sql.tables import check_target_audit

MERGES = frozenset({SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE})
_STATE = (("key_hash", "VARCHAR"), ("column_name", "VARCHAR"), ("locked", "BOOLEAN"))


def legacy_names(session: Session) -> tuple[str, str]:
    """Resolve obsolete side-table names solely for the upgrade refusal."""
    from etl_craft.engine.repository.normalization import object_identity

    parts = object_identity(session.target, None, session.dialect.sqlglot_dialect)
    catalog, schema, _ = parts
    suffix = sha256_hex(".".join(str(p) for p in parts).lower().encode())[:20]
    return (
        f"{catalog}.{schema}.etl_protection_{suffix}",
        f"{catalog}.{schema}.etl_fingerprints_{suffix}",
    )


def refuse_legacy(session: Session) -> None:
    """Refuse obsolete protection before changing warehouse or audit state."""
    names = legacy_names(session)
    found = session.relation_types(names)
    if found:
        tables = ", ".join(names[i] for i in found)
        raise SqlGuardError(
            f"{session.target}: old protection side tables found: "
            f"{tables}; expected in-row protection; back up, "
            "recreate the target, and re-apply the locks"
        )


def exists(session: Session) -> bool:
    """Detect activated in-row protection without interpreting business values."""
    refuse_legacy(session)
    if session.protection_active is False:
        return False
    if "etl_protection" not in {c.lower() for c, _ in session.target_columns()}:
        return False
    row = session.run(
        f"SELECT ETL_PROTECTION AS protection FROM {session.target} "
        "WHERE ETL_PROTECTION IS NOT NULL AND ETL_PROTECTION "
        "NOT LIKE :baseline LIMIT 1",
        {"baseline": '%"revision":0}'},
        step="read in-row protection state",
    ).first()
    if row is None:
        return False
    try:
        state = json.loads(row.protection)
    except (ValueError, TypeError) as error:
        raise SqlGuardError(
            f"{session.target}: malformed ETL_PROTECTION; expected "
            "format 1; restore a consistent backup"
        ) from error
    if not isinstance(state, dict) or state.get("format") != 1:
        raise SqlGuardError(
            f"{session.target}: invalid protection format; expected "
            "canonical format 1; restore a consistent backup"
        )
    return True


def refuse_replacement(session: Session) -> None:
    """Keep replacement actions from destroying protected rows."""
    if exists(session):
        raise SqlGuardError(
            f"{session.target}: {session.action} cannot replace "
            "protected SCD data; use its SCD merge or authorized "
            "edit/unlock"
        )


class Protection:
    """Stage exact events and row-local protection for one target mutation."""

    def __init__(self, session: Session, task: SqlTask) -> None:
        """Bind the admitted business shape and typed hash expressions."""
        self.session, self.task = session, task
        columns = tuple(c for c, _ in check_target_audit(session, task.action))
        if problems := type_problems(
            session.dialect, session.target, session.hash_types(session.target)
        ):
            raise SqlGuardError("; ".join(problems))
        self.business = business_columns(columns)
        names = {c.lower(): c for c in columns}
        self.key_columns = tuple(names[c.lower()] for c in task.merge_key)
        self.contract = contract(task, self.business)
        self.states: dict[str, RowProtection] = {}
        self.stamps: dict[str, str | None] = {}
        self.prevented_rows = self.prevented_values = 0
        self.row_lock = False
        self.business_changes = False
        self.mutating_rows = 0
        self.request: ProtectionRequest | None = None
        self.request_id: str | None = None
        self.state_table = session.scratch("lock_state")
        types = session.hash_types(session.target)

        def hashed(names: tuple[str, ...]) -> str:
            return session.dialect.hash_expression(
                [f"t.{c}" for c in names], [types[c.lower()] for c in names]
            )

        self.sql = ProtectionSql(
            session.target,
            self.state_table,
            hashed(task.merge_key),
            {c: hashed((c,)) for c in self.business},
            fingerprint(session, self.business, "t", "t.ETL_PROTECTION"),
        )
        self.unlocking: set[str] = set()
        self.activating = False
        self.enabled = False
        self.loaded = False

    def acquire(self) -> None:
        """Check the upgrade boundary and acquire the provider's native lock."""
        refuse_legacy(self.session)
        if sql := self.session.dialect.protection_lock_sql(self.session.target):
            self.session.run(sql, step="lock protected business data")

    def enable(self, request: ProtectionRequest) -> None:
        """Activate protection only for unambiguous non-NULL business keys."""
        self.check()
        invalid = self.session.count(
            self.sql.invalid_keys(
                self.task.merge_key, scd2=self.task.action == SqlAction.SCD2_MERGE
            ),
            step="validate protected business keys",
        )
        if invalid:
            raise SqlGuardError(
                f"{self.session.target}: {invalid} NULL or duplicate "
                "current business keys; expected unique non-NULL "
                "keys; repair the target before protection"
            )
        self.enabled = True
        self.activating = True
        self.request = request

    def check(self) -> None:
        """Refuse rows whose business values or protection state drifted."""
        self.acquire()
        if self.session.count(self.sql.drift(), step="check unobserved writes"):
            raise SqlGuardError(
                f"{self.session.target}: unobserved warehouse writes "
                "differ from the in-row fingerprint; expected authenticated "
                "writers; restore a consistent backup and route "
                "outside writers through the service"
            )

    def _load(self, stage: str | None = None, key: str | None = None) -> None:
        s = self.session
        cells = "".join(
            f",{hashed} AS cell_{i}" for i, hashed in enumerate(self.sql.cell_hashes.values())
        )
        predicate = "TRUE"
        params: dict[str, object] = {}
        if stage is not None:
            matched = " AND ".join(f"t.{c}=s.{c}" for c in self.task.merge_key)
            predicate = f"EXISTS (SELECT 1 FROM {stage} s WHERE {matched})"
        elif key is not None:
            predicate = f"{self.sql.key_hash}=:selected_key"
            params["selected_key"] = key
        rows = s.run(
            f"SELECT {self.sql.key_hash} AS key_hash,t.ETL_PROTECTION "
            f"AS protection,t.ETL_PROTECTION_REQUEST_ID AS request_id{cells} "
            f"FROM ({self.sql.current()}) t WHERE {predicate}",
            params,
            step="read current locks and writers",
        )
        for row in rows.mappings():
            state = RowProtection.load(row["protection"], self.contract, s.target)
            self.enabled |= bool(state.revision)
            for i, column in enumerate(self.business):
                state.cells.setdefault(
                    column,
                    {
                        "value_hash": row[f"cell_{i}"],
                        "locked": False,
                        "writer": None,
                        "writer_kind": None,
                        "actor": None,
                        "actor_kind": None,
                        "happened_at": self.request.now.isoformat() if self.request else None,
                        "request_id": None,
                        "reason": "",
                        "revision": 0,
                    },
                )
            self.states[str(row["key_hash"])] = state
            self.stamps[str(row["key_hash"])] = row["request_id"]
        data = [
            (key, column, cell.get("locked"))
            for key, state in self.states.items()
            for column, cell in state.cells.items()
        ]
        self.state_table = self._table(self.state_table, _STATE, data)
        self.sql = ProtectionSql(
            self.sql.target,
            self.state_table,
            self.sql.key_hash,
            self.sql.cell_hashes,
            self.sql.row_hash,
        )
        self.loaded = True

    def _table(
        self, name: str, columns: tuple[tuple[str, str], ...], rows: Sequence[tuple[object, ...]]
    ) -> str:
        s = self.session
        columns = tuple(
            (column, s.dialect.string_type if kind == "VARCHAR" else kind)
            for column, kind in columns
        )
        if not rows:
            empty = ", ".join(f"CAST(NULL AS {kind}) AS {column}" for column, kind in columns)
            return s.create_scratch(
                name, f"SELECT {empty} WHERE 1=0", step="stage bounded protection metadata"
            )
        for start in range(0, len(rows), 64):
            batch = rows[start : start + 64]
            params = {
                f"v_{i}_{j}": value for i, row in enumerate(batch) for j, value in enumerate(row)
            }
            body = bound_relation(columns, len(batch))
            if start == 0:
                previous = s.bindings
                s.bindings = previous | params
                try:
                    name = s.create_scratch(name, body, step="stage bounded protection metadata")
                finally:
                    s.bindings = previous
            else:
                s.run(f"INSERT INTO {name} {body}", params, step="bind protection metadata")
        return name

    def stage(self, stage: str, *, delete: bool = False) -> str:
        """Overlay locked cells before computing hashes or deleting rows."""
        self.check()
        if not self.loaded:
            self._load(stage)
        s = self.session
        columns = tuple(c for c, _ in s.columns(stage))
        attempts = self.sql.prevented(stage, columns, delete=delete)
        self.prevented_rows += s.count(
            f"SELECT COUNT(DISTINCT key_hash) FROM ({attempts}) p", step="prevented row changes"
        )
        self.prevented_values += s.count(
            f"SELECT COUNT(*) FROM ({attempts}) p", step="prevented value changes"
        )
        protected = s.scratch("protected")
        protected = s.create_scratch(
            protected,
            self.sql.protect_stage(
                stage, columns, delete=delete, preserve=self.task.preserve_target
            ),
            step="respect human locks",
        )
        s.drop(stage)
        return protected

    def _incoming(self, stage: str, condition: str) -> Sequence[RowMapping]:
        """Read hashes only from the already-protected effective stage."""
        s = self.session
        cells = "".join(
            f",{hashed} AS cell_{i}" for i, hashed in enumerate(self.sql.cell_hashes.values())
        )
        key = " AND ".join(f"p.{c}=t.{c}" for c in self.task.merge_key)
        active = " AND p.ACTIVE_FLAG='Y'" if self.task.action == SqlAction.SCD2_MERGE else ""
        same = condition.replace("t.", "p.").replace("s.", "t.")
        selected = (
            "TRUE"
            if self.row_lock
            or self.activating
            or (
                self.request is not None
                and self.request.upload_id is not None
                and self.request.actor.kind == ActorKind.USER
            )
            else f"NOT EXISTS (SELECT 1 FROM {s.target} p WHERE {key}{active} AND NOT ({same}))"
        )
        locked = "t.LOCKED" if "locked" in {c.lower() for c, _ in s.columns(stage)} else "NULL"
        return (
            s.run(
                f"SELECT {self.sql.key_hash} AS key_hash,{locked} AS upload_locked{cells},NOT "
                f"EXISTS (SELECT 1 FROM {s.target} p WHERE {key}{active} "
                f"AND NOT ({same})) AS mutating FROM {stage} t WHERE "
                f"{selected}",
                step="fingerprint effective values",
            )
            .mappings()
            .all()
        )

    def prepare(self, stage: str, request: ProtectionRequest, condition: str) -> str:
        """Compute exact cell events from effective staged values before the target MERGE."""
        if not self.loaded:
            self._load(stage)
        incoming = self._incoming(stage, condition)
        from etl_craft.handlers.sql.protection_events import plan

        events, changed = plan(self, incoming, request)
        if events:
            self.request_id = self.pending(events)
        return self._stage_metadata(stage, incoming, changed, request)

    def _stage_metadata(
        self,
        stage: str,
        incoming: Sequence[RowMapping],
        changed: dict[str, dict[str, str]],
        request: ProtectionRequest,
    ) -> str:
        s = self.session
        metadata = []
        for row in incoming:
            key = str(row["key_hash"])
            state = self.states.get(key) or RowProtection(self.contract)
            if key in changed:
                assert self.request_id is not None
                operation = replace(request, request_id=self.request_id)
                if key in self.unlocking:
                    operation = replace(
                        operation, reason=f"upload {request.upload_id}: LOCKED=false"
                    )
                    state.unlocked((), operation)
                state.changed(
                    changed[key],
                    operation,
                    inserted=key not in self.states,
                    row_lock=self.row_lock,
                    locked=key not in self.unlocking,
                )
            metadata.append(
                (key, state.encoded(), self.request_id if key in changed else self.stamps.get(key))
            )
        table = self._table(
            s.scratch("protection_values"),
            (("key_hash", "VARCHAR"), ("protection", "VARCHAR"), ("request_id", "VARCHAR")),
            metadata,
        )
        result = s.scratch("effective_protection")
        hashed = self.sql.key_hash.replace("t.", "v.")
        fp = fingerprint(s, self.business, "v", "m.protection")
        result = s.create_scratch(
            result,
            f"SELECT v.*,m.protection AS ETL_PROTECTION,{fp} "
            "AS ETL_ROW_FINGERPRINT,m.request_id AS ETL_PROTECTION_REQUEST_ID "
            f"FROM {stage} v JOIN {table} m ON m.key_hash={hashed}",
            step="stage atomic business and protection values",
        )
        s.drop(stage)
        return result

    def pending(self, events: list[ProtectionEvent]) -> str:
        """Append bounded hash-only intent before the warehouse mutation."""
        from etl_craft.handlers.protection_recovery import pending

        store = self.session.protection_store
        assert store is not None
        request = pending(
            store,
            self.session.target,
            events,
            self.session.protection_requests,
            self.request.upload_id if self.request else None,
        )
        assert request is not None
        return request

    def refresh(self, key: str) -> None:
        """Read the just-written row state rather than an earlier mutation's staging cache."""
        self.session.drop(self.state_table)
        self.state_table = self.session.scratch("lock_state")
        self.loaded = False
        self.states.clear()
        self.stamps.clear()
        self.check()
        self._load(key=key)

    def metadata_only(self, stage: str) -> None:
        """Change lock state and its fingerprint together without creating an SCD version."""
        s = self.session
        key = self.sql.key_hash.replace("t.", "v.")
        source = (
            f"(SELECT t.ROW_ID AS ROW_ID,v.ETL_PROTECTION,v.ETL_ROW_FINGERPRINT,"
            f"v.ETL_PROTECTION_REQUEST_ID FROM {stage} v JOIN ({self.sql.current()}) t "
            f"ON {self.sql.key_hash}={key})"
        )
        assignments = {
            c: f"s.{c}"
            for c in ("ETL_PROTECTION", "ETL_ROW_FINGERPRINT", "ETL_PROTECTION_REQUEST_ID")
        }
        s.run(
            matched_merge(s.target, source, assignments)
            if s.dialect.supports_insert_merge(s.conn)
            else s.dialect.update_from_stage(s.target, source, ("ROW_ID",), assignments, "TRUE"),
            step="merge lock state and fingerprint",
        )

    def unlock(self, key: str, columns: tuple[str, ...], request: ProtectionRequest) -> None:
        """Retain actual value writers while recording the actor releasing their locks."""
        self.check()
        if not self.loaded:
            self._load(key=key)
        state = self.states.get(key)
        if state is None:
            return
        names = tuple(
            c
            for c, cell in state.cells.items()
            if cell.get("locked") and (not columns or c in columns)
        )
        if not names:
            return
        self.request_id = self.pending(
            [
                ProtectionEvent(
                    ProtectionKind.UNLOCK,
                    key,
                    names[start : start + MAX_PROTECTION_COLUMNS],
                    tuple(
                        str(state.cells[c]["value_hash"])
                        if state.cells[c]["value_hash"] is not None
                        else None
                        for c in names[start : start + MAX_PROTECTION_COLUMNS]
                    ),
                )
                for start in range(0, len(names), MAX_PROTECTION_COLUMNS)
            ]
        )
        state.unlocked(columns, replace(request, request_id=self.request_id))
        s = self.session
        table = self._table(
            s.scratch("unlocked"),
            (("key_hash", "VARCHAR"), ("protection", "VARCHAR"), ("request_id", "VARCHAR")),
            [(key, state.encoded(), self.request_id)],
        )
        stage = s.scratch("unlock_values")
        fp = fingerprint(s, self.business, "t", "m.protection")
        stage = s.create_scratch(
            stage,
            f"SELECT t.*,m.protection AS new_protection,{fp} "
            "AS new_fingerprint,m.request_id AS new_request_id "
            f"FROM ({self.sql.current()}) t JOIN {table} m ON "
            f"{self.sql.key_hash}=m.key_hash",
            step="stage unlocked state",
        )
        source = f"(SELECT ROW_ID,new_protection,new_fingerprint,new_request_id FROM {stage})"
        assignments = {
            "ETL_PROTECTION": "s.new_protection",
            "ETL_ROW_FINGERPRINT": "s.new_fingerprint",
            "ETL_PROTECTION_REQUEST_ID": "s.new_request_id",
        }
        s.run(
            matched_merge(s.target, source, assignments)
            if s.dialect.supports_insert_merge(s.conn)
            else s.dialect.update_from_stage(s.target, source, ("ROW_ID",), assignments, "TRUE"),
            step="merge unlocked state",
        )


def for_task(session: Session, task: SqlTask) -> Protection | None:
    """Bind the recorded merge contract when the target is protected."""
    if not exists(session):
        return None
    if task.action not in MERGES | {SqlAction.DELETE_ROWS, SqlAction.SETUP_TABLE}:
        refuse_replacement(session)
    sample = session.run(
        f"SELECT ETL_PROTECTION AS protection FROM {session.target} "
        "WHERE ETL_PROTECTION IS NOT NULL AND ETL_PROTECTION NOT LIKE :baseline LIMIT 1",
        {"baseline": '%"revision":0}'},
        step="read protected writer contract",
    ).scalar_one()
    if task.action not in MERGES:
        saved = json.loads(sample)["contract"]
        if task.action == SqlAction.DELETE_ROWS and task.merge_key != tuple(saved[1]):
            raise SqlGuardError(
                f"{session.target}: DELETE_ROWS MERGE_KEY={task.merge_key}; expected "
                f"{tuple(saved[1])} from protection; configure the same business key"
            )
        task = replace(
            task,
            action=SqlAction(saved[0]),
            merge_key=tuple(saved[1]),
            merge_compare_columns=tuple(saved[2]),
        )
    guard = Protection(session, task)
    RowProtection.load(sample, guard.contract, session.target)
    guard.check()
    return guard


def refuse_evidence_target(session: Session) -> None:
    """Reserve obsolete protection table names against task writes."""
    if re.fullmatch(r"etl_(protection|fingerprints)_[0-9a-f]{20}", session.table.lower()):
        raise SqlGuardError(
            f"{session.target}: old protection side table; expected "
            "an in-row business target; back up, recreate the "
            "business target, and re-apply locks"
        )
