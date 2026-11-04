"""Task metadata and progress without lending an Engine DB connection to a handler."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.engine import Connection, Engine

from etl_craft.config import ConnectorConfig
from etl_craft.config.targets import active_catalog
from etl_craft.core.actor import current_actor
from etl_craft.core.business_rules import RULE_TEXT_LIMIT, table_result
from etl_craft.core.definitions import Definition, using
from etl_craft.core.enums import BusinessRuleLevel, Handler, RunStatus, SqlAction, YesNo
from etl_craft.core.erasure import ErasureReport
from etl_craft.core.errors import HandlerError, StaleTransitionError
from etl_craft.core.items import ItemRecord, ItemState, ItemStore
from etl_craft.core.landing import GENERATED_COLUMNS, LandingContract
from etl_craft.core.ownership import ResourceLocker, attempt_holder
from etl_craft.core.protection import (
    ProtectionCandidates,
    ProtectionMatches,
    ProtectionPage,
    ProtectionReport,
)
from etl_craft.core.text import qualify
from etl_craft.core.time import as_utc
from etl_craft.core.uploads import UploadFile
from etl_craft.engine import locks, resource_locks, transitions
from etl_craft.engine.agent_state import fence
from etl_craft.engine.alerts import AlertState, read_alert
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.business_rules import (
    BusinessRule,
    RuleRunBinding,
    begin_rule_run,
    clear_rule_keys,
    fetch_active_rule_keys,
    fetch_business_rules_for_task,
    finish_rule_run,
    flag_rule_keys,
)
from etl_craft.engine.repository.hash_versions import (
    clear_hash_version,
    fetch_target_contract,
    save_hash_version,
    save_view_statement,
)
from etl_craft.engine.repository.offsets import StoredOffset, fetch_task_offset
from etl_craft.engine.repository.tasks import (
    TargetTask,
)
from etl_craft.engine.resource_locks import currently_holds, holder_tag
from etl_craft.engine.timestamp_windows import (
    TimestampWindow,
    WindowDefinition,
    admit_window,
    recorded_start,
)


@dataclass(frozen=True)
class TaskIdentity:
    """The exact run and attempt a caller may read and change."""

    pipeline_id: int
    task_id: int
    pipeline_run_id: int
    task_run_id: int
    attempt_id: int | None
    owner: str | None
    credential_digest: str | None = None

    @property
    def holder_id(self) -> str:
        """Use the credential namespace for agents and the process owner for local attempts."""
        assert self.attempt_id is not None
        return attempt_holder(self.attempt_id, self.credential_digest or self.owner or "")


@dataclass(frozen=True)
class TaskState:
    """A task's metadata, checkpoint and related writers at the time of the read."""

    offset: StoredOffset | None
    rules: tuple[BusinessRule, ...]
    peers: tuple[TargetTask, ...]
    peer_statuses: dict[str, str | None]
    merge_conflict: str | None
    target: str | None = None
    contract: TargetState | None = None
    rule_flags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    landing: LandingContract | None = None


@dataclass(frozen=True)
class TargetState:
    """Published state is read under the same lock as the warehouse mutation."""

    hash_version: int | None
    view_statement: str | None


@dataclass(frozen=True)
class TargetPublication:
    """State to publish only after the corresponding warehouse transaction committed."""

    target: str
    hash_version: int | None = None
    clear_hash: bool = False
    view_statement: str | None = None


@dataclass(frozen=True)
class RuleEnding:
    """One rule's keys and ending commit together under its task attempt."""

    rule_id: int
    rule_run_id: int
    status: RunStatus
    new_keys: tuple[str, ...] = ()
    passing_keys: tuple[str, ...] = ()
    passed: YesNo | None = None
    observed: str | None = None
    detail: str | None = None


class TaskStore(ResourceLocker, ItemStore, Protocol):
    """The local and HTTP task backends expose the same bounded operations."""

    def protection_match(self, target: str, candidates: ProtectionCandidates) -> ProtectionMatches:
        """Compare bounded candidates only for this target's pending deletion recovery."""
        ...

    def protection_read(self, target: str, cursor: int = 0) -> ProtectionPage:
        """Read a bounded page under the same admitted-target ownership fence."""
        ...

    def protection_event(self, target: str, report: ProtectionReport) -> str:
        """Append an intent or idempotent outcome through the common event service."""
        ...

    def erasure(self) -> ErasureReport:
        """Execute the admitted erasure without returning personal keys."""
        ...

    def upload_files(self) -> tuple[UploadFile, ...]:
        """Read and verify the admitted files before exposing them to a script."""
        ...

    def validation_result(self, upload_id: int, reason: str | None) -> None:
        """Record this validator's decision for one admitted file."""
        ...

    def alert(self, pipelines: str | None) -> AlertState:
        """Read this task's run report and requested pipeline digests."""
        ...

    def state(self, sql_action: str | None = None) -> TaskState:
        """Read this task's metadata and recorded checkpoints."""
        ...

    def target(self, target: str) -> TargetState:
        """Read a target's published state under its resource ownership."""
        ...

    def publish(self, publication: TargetPublication) -> None:
        """Publish the warehouse commit's hash or view contract."""
        ...

    def watermark(self, start: str, end: str) -> None:
        """Record a staged range without advancing its checkpoint."""
        ...

    def window(self, definition: WindowDefinition) -> TimestampWindow:
        """Admit one retry-stable timestamp window before executing SQL."""
        ...

    def begin_rule(self, rule_id: int) -> RuleRunBinding:
        """Bind a rule to this task run, retaining a successful result on retry."""
        ...

    def rule_keys(self, rule_id: int) -> set[str]:
        """Read a rule's currently active flagged keys."""
        ...

    def end_rule(self, ending: RuleEnding) -> None:
        """Record a rule's flags and ending together."""
        ...


@dataclass(frozen=True)
class LocalTaskStore:
    """Keep SQL and fenced lifecycle decisions in the Engine DB service."""

    engine: Engine
    config: ConnectorConfig
    identity: TaskIdentity
    locks: ResourceLocker
    definition: Definition | None = None
    _contracts: dict[str, TargetState] = field(default_factory=dict, compare=False)
    _erasure_target: str | None = None
    parameters: Mapping[str, str] = field(default_factory=dict, repr=False)

    def erasure_target(self, target: str) -> LocalTaskStore:
        """Bind a host-validated lineage target without exposing an agent target override."""
        from etl_craft.engine.repository.tasks import fetch_task_execution_detail

        with self.engine.connect() as conn:
            self._assert(conn)
            with using(self.definition):
                handler = fetch_task_execution_detail(conn, self.identity.task_id).handler
            if handler != Handler.ERASURE:
                raise HandlerError(
                    f"attempt {self.identity.attempt_id}, target {target}: handler={handler}; "
                    "expected ERASURE for a lineage target; use the admitted SQL target"
                )
        return replace(self, _erasure_target=target)

    @classmethod
    def standalone(
        cls, engine: Engine, config: ConnectorConfig, locker: ResourceLocker
    ) -> LocalTaskStore:
        """Bind in-process maintenance to its explicit actor and target ownership."""
        return cls(engine, config, TaskIdentity(0, 0, 0, 0, None, None), locker)

    def protection_read(self, target: str, cursor: int = 0) -> ProtectionPage:
        """Share one fenced event-store implementation with the HTTP provider."""
        from etl_craft.engine.protection_events import fenced_read

        with self.engine.begin() as conn:
            canonical, fencing = self._protection_scope(conn, target)
            return fenced_read(conn, canonical, fencing, cursor, config=self.config)

    def protection_match(self, target: str, candidates: ProtectionCandidates) -> ProtectionMatches:
        """Use the same host matcher as the fenced agent report."""
        from etl_craft.engine.protection_matching import match

        with self.engine.begin() as conn:
            canonical, fencing = self._protection_scope(conn, target)
            return match(conn, self.config, canonical, fencing, candidates)

    def protection_event(self, target: str, report: ProtectionReport) -> str:
        """Never append an event for an unfenced target or another live creator."""
        from etl_craft.config.privacy import privacy_secret
        from etl_craft.engine.privacy import guarded
        from etl_craft.engine.protection_events import append, append_fenced

        key = privacy_secret(self.config)
        with guarded(self.config), self.engine.begin() as conn:
            canonical, fencing = self._protection_scope(conn, target)
            if request := append_fenced(conn, canonical, report, fencing, key):
                return request
            canonical = self._protection_fence(conn, target)
            from etl_craft.engine.protection_events import target_identity

            physical = target_identity(self.config, target)[1]
            return append(
                conn, canonical, report, self.identity.attempt_id, physical, privacy_key=key
            )

    def _protection_scope(self, conn: Connection, target: str) -> tuple[str, dict[str, object]]:
        from etl_craft.core.errors import PermissionDeniedError
        from etl_craft.engine.protection_events import target_identity
        from etl_craft.engine.repository.tasks import fetch_task_parameters

        identity = self.identity
        where = f"attempt {identity.attempt_id}, target {target}"
        catalog = active_catalog(self.config)
        canonical, physical = target_identity(self.config, target)
        key = locks.target(physical, catalog).key
        if identity.attempt_id is None:
            if not currently_holds(key):
                raise StaleTransitionError(
                    f"{where}: target lock is not held; acquire it before protection work"
                )
            holder = resource_locks.current_holder("")
            holder_id, owner = holder.holder_id, holder.owner
        else:
            with using(self.definition):
                expected = self._erasure_target or fetch_task_parameters(
                    conn, identity.task_id
                ).get("TARGET_OBJECT")
            if expected is None or target_identity(self.config, expected)[0] != canonical:
                raise PermissionDeniedError(
                    f"{where}: admitted-target check failed; "
                    "use only this attempt's admitted target"
                )
            holder_id, owner = identity.holder_id, identity.owner or ""
        validators = (
            [
                row["task_id"]
                for row in self.definition.rows["CFG_TASKS"]
                if row["pipeline_id"] == identity.pipeline_id
                and row["handler"] == Handler.FILE_VALIDATION
                and row["active_flag"] == YesNo.YES
            ]
            if self.definition is not None
            else []
        )
        return canonical, {
            "attempt_id": identity.attempt_id,
            "task_run_id": identity.task_run_id,
            "pipeline_run_id": identity.pipeline_run_id,
            "validator_id": validators[0] if len(validators) == 1 else None,
            "owner": identity.owner or "",
            "key": key,
            "holder": holder_id,
            "lock_owner": owner,
        }

    def _protection_fence(self, conn: Connection, target: str) -> str:
        where = f"attempt {self.identity.attempt_id}, target {target}"
        try:
            self._assert(conn)
        except StaleTransitionError as error:
            raise StaleTransitionError(
                f"{where}: live-attempt/token check failed; "
                "stop this writer and obtain a fresh attempt"
            ) from error
        canonical, fencing = self._protection_scope(conn, target)
        owned = conn.execute(
            statement(conn, "resource_lock_owned"),
            {"key": fencing["key"], "holder": fencing["holder"], "owner": fencing["lock_owner"]},
        ).scalar_one_or_none()
        if owned is None:
            raise StaleTransitionError(
                f"{where}: target-lock check failed; acquire its live lock before reporting"
            )
        return canonical

    def erasure(self) -> ErasureReport:
        """Require local execution to pass its Engine DB directly to the handler."""
        raise HandlerError("local ERASURE requires its Engine DB backend; use the task runner")

    def upload_files(self) -> tuple[UploadFile, ...]:
        """Use the same fenced storage stream as API-only agents."""
        from etl_craft.core.upload_copy import verified_upload
        from etl_craft.engine.upload_files import stream_upload
        from etl_craft.engine.uploads import run_uploads

        with self.engine.connect() as conn:
            from etl_craft.engine.repository.tasks import fetch_task_execution_detail

            with using(self.definition):
                detail = fetch_task_execution_detail(conn, self.identity.task_id).handler
            uploads = run_uploads(conn, self.identity.pipeline_run_id, detail)
        root = self.config.host_dir / ".upload_inputs" / str(self.identity.attempt_id)
        return tuple(
            verified_upload(
                root,
                upload,
                stream_upload(self.engine, self.config, self.identity, upload.upload_id),
            )
            for upload in uploads
        )

    def validation_result(self, upload_id: int, reason: str | None) -> None:
        """Fence each per-file decision against this validator's live attempt."""
        from etl_craft.engine.uploads import validation_result

        with self.engine.begin() as conn:
            self._assert(conn)
            from etl_craft.engine.repository.tasks import fetch_task_execution_detail

            with using(self.definition):
                handler = fetch_task_execution_detail(conn, self.identity.task_id).handler
            validation_result(conn, self.identity.pipeline_run_id, handler, upload_id, reason)

    @property
    def session_tag(self) -> str:
        """Tag the task independently of its metadata service connection."""
        if self.identity.attempt_id is not None:
            return holder_tag(self.identity.holder_id)
        return self.locks.session_tag

    def _assert(self, conn: Connection) -> None:
        identity = self.identity
        if identity.attempt_id is not None:
            task_run_id = fence(conn, identity.attempt_id, identity.owner or "")
            if task_run_id != identity.task_run_id:
                raise StaleTransitionError(
                    f"attempt {identity.attempt_id}: task run {identity.task_run_id} differs "
                    f"from admitted {task_run_id}; use its admitted identity"
                )

    @contextmanager
    def hold(self, key: int, name: str, wait_seconds: float) -> Iterator[None]:
        """Use the common target, event and warehouse ownership service."""
        with self.locks.hold(key, name, wait_seconds):
            self._contracts.clear()
            try:
                yield
            finally:
                self._contracts.clear()

    def alert(self, pipelines: str | None) -> AlertState:
        """Read the exact run's report, using the deployment's SLA policy."""
        with using(self.definition):
            identity = self.identity
            with self.engine.connect() as conn:
                self._assert(conn)
                return read_alert(
                    conn,
                    identity.pipeline_id,
                    identity.pipeline_run_id,
                    identity.task_id,
                    self.config.limits.enforce_sla,
                    pipelines,
                )

    def state(self, sql_action: str | None = None) -> TaskState:
        """Read only metadata belonging to the selected task and its run."""
        from etl_craft.engine.repository.pipelines import current_project_id, selected_project

        project_id = current_project_id()
        if self.definition is not None:
            pipeline = self.definition.row(
                "CFG_PIPELINES", "pipeline_id", self.identity.pipeline_id
            )
            project_id = int(str(pipeline.get("project_id", 1)))
        with using(self.definition), selected_project(project_id):
            identity = self.identity
            with self.engine.connect() as conn:
                self._assert(conn)
                if sql_action is not None:
                    state = self._sql_state(conn, sql_action)
                    return (
                        state
                        if sql_action == SqlAction.DROP_TABLE
                        else replace(state, rule_flags=self._rule_scopes(conn))
                    )
                return TaskState(
                    fetch_task_offset(conn, identity.task_id),
                    tuple(fetch_business_rules_for_task(conn, identity.task_id)),
                    (),
                    {},
                    None,
                    landing=self._landing_contract(conn),
                )

    def _landing_contract(self, conn: Connection) -> LandingContract | None:
        """Expose only the declared landing target and active column types of this task."""
        from etl_craft.engine.repository.source_columns import fetch_source_columns
        from etl_craft.engine.repository.tasks import fetch_task_parameters

        params = fetch_task_parameters(conn, self.identity.task_id)
        target = params.get("TARGET_OBJECT")
        if target is None:
            return None
        catalog = active_catalog(self.config)
        canonical = qualify(target, catalog)
        columns = tuple(
            (c.column_name, c.data_type)
            for c in fetch_source_columns(conn)
            if qualify(c.table_name, catalog).lower() == canonical.lower()
            and c.column_name.lower() not in GENERATED_COLUMNS
        )
        return LandingContract(self.identity.task_id, canonical, columns)

    def _rule_scopes(self, conn: Connection) -> dict[str, tuple[str, ...]]:
        """Read only scopes declared by this attempt's admitted SELECT."""
        from etl_craft.config.project import sql_script
        from etl_craft.core.rule_flags import parse_scopes
        from etl_craft.engine.rule_scopes import keys

        params = self.parameters
        raw = params.get("SELECT_QUERY", "")
        if name := params.get("SCRIPT_FILE"):
            raw = sql_script(self.config, name).read_text(encoding="utf-8")
        return {
            scope.token: keys(conn, self.identity.task_id, self.identity.pipeline_run_id, scope)
            for scope in parse_scopes(raw)
        }

    def _sql_state(self, conn: Connection, sql_action: str) -> TaskState:
        """Read checkpoint, peer outcomes and target contract from one database snapshot."""
        identity = self.identity
        rows = conn.execute(
            statement(conn, "sql_task_state"),
            {
                "task_id": identity.task_id,
                "pipeline_id": identity.pipeline_id,
                "pipeline_run_id": identity.pipeline_run_id
                if sql_action == SqlAction.DROP_TABLE
                else None,
                "sql_action": sql_action,
                "catalog": active_catalog(self.config)
                if self.config.warehouse is not None
                else None,
            },
        ).all()
        row = rows[0]
        target = f"{row.catalog_name}.{row.schema_name}.{row.table_name}"
        contract = TargetState(row.hash_version, row.statement_sha256)
        if currently_holds(locks.target(target, row.catalog_name).key):
            self._contracts[target] = contract
        return TaskState(
            StoredOffset(
                row.offset_type,
                row.offset_value,
                row.pending_task_run_id,
                None if row.pending_upper_bound is None else as_utc(row.pending_upper_bound),
            )
            if row.offset_type is not None
            else None,
            (),
            tuple(
                TargetTask(peer.task_id, peer.task_code, peer.sql_action)
                for peer in rows
                if peer.task_id is not None
            ),
            {str(peer.task_id): peer.status for peer in rows if peer.task_id is not None}
            if sql_action == SqlAction.DROP_TABLE
            else {},
            row.merge_conflict
            if sql_action in {SqlAction.SCD1_MERGE, SqlAction.SCD2_MERGE}
            else None,
            target,
            contract,
        )

    def target(self, target: str) -> TargetState:
        """Read the published contract; warehouse state is never guessed."""
        if target.lower() in self._contracts:
            return self._contracts[target.lower()]
        with self.engine.connect() as conn:
            self._assert(conn)
            return TargetState(*fetch_target_contract(conn, target))

    def publish(self, publication: TargetPublication) -> None:
        """Publish only after the caller's warehouse commit."""
        known = self._contracts.get(publication.target.lower())
        if (
            publication.clear_hash
            and known is not None
            and known.hash_version is None
            and publication.hash_version is None
            and publication.view_statement is None
        ):
            return
        with self.engine.begin() as conn:
            self._assert(conn)
            if self.identity.attempt_id is not None:
                key = locks.target(publication.target, active_catalog(self.config)).key
                owned = conn.execute(
                    statement(conn, "resource_lock_owned"),
                    {
                        "key": key,
                        "holder": self.identity.holder_id,
                        "owner": self.identity.owner,
                    },
                ).scalar_one_or_none()
                if owned is None:
                    raise StaleTransitionError(
                        f"target {publication.target}: attempt has no live resource lock; "
                        "stop this writer"
                    )
            if publication.clear_hash:
                clear_hash_version(conn, publication.target)
            if publication.hash_version is not None:
                save_hash_version(conn, publication.target, publication.hash_version)
            if publication.view_statement is not None:
                save_view_statement(conn, publication.target, publication.view_statement)
        self._contracts.pop(publication.target.lower(), None)

    def watermark(self, start: str, end: str) -> None:
        """Fence the staged range to the current attempt without moving the offset."""
        identity = self.identity
        with self.engine.begin() as conn:
            self._assert(conn)
            transitions.record_watermark_range(
                conn,
                identity.task_run_id,
                start,
                end,
                attempt_id=identity.attempt_id,
                owner=identity.owner,
            )

    def window(self, definition: WindowDefinition) -> TimestampWindow:
        """Serialize admission with source starts and publish range evidence before SQL."""
        identity = self.identity
        with self.engine.begin() as conn:
            self._assert(conn)
            window = admit_window(
                conn,
                identity.task_id,
                identity.task_run_id,
                recorded_start(conn, identity.task_run_id, identity.attempt_id),
                definition,
            )
            transitions.record_watermark_range(
                conn,
                identity.task_run_id,
                window.low.isoformat(),
                window.high.isoformat(),
                attempt_id=identity.attempt_id,
                owner=identity.owner,
            )
            return window

    def items(self) -> ItemState:
        """Read durable items and this attempt's actual admitted memory."""
        from etl_craft.engine import items

        with self.engine.begin() as conn:
            self._assert(conn)
            reservation = conn.execute(
                statement(conn, "item_reservation"),
                {
                    "attempt_id": self.identity.attempt_id,
                },
            ).one()
            return ItemState(
                items.latest(conn, self.identity.task_run_id),
                int(reservation.memory_mb),
                float(reservation.cpu),
            )

    def prepare_items(self, keys: tuple[str, ...]) -> None:
        """Register keys and retain successes in one serialized, owned transaction."""
        from etl_craft.core.items import bounded_keys
        from etl_craft.engine import controls, items

        checked = bounded_keys(keys, 1000)
        with self.engine.begin() as conn:
            controls.lock_run(conn, self.identity.pipeline_run_id)
            self._assert(conn)
            assert self.identity.attempt_id is not None
            items.prepare(conn, self.identity.task_run_id, self.identity.attempt_id, checked)

    def item_event(self, event: ItemRecord) -> ItemRecord:
        """Serialize item results with operator decisions and reject an expired owner."""
        from etl_craft.engine import controls, items

        with self.engine.begin() as conn:
            controls.lock_run(conn, self.identity.pipeline_run_id)
            self._assert(conn)
            assert self.identity.attempt_id is not None
            from etl_craft.engine.item_offsets import check

            with using(self.definition):
                check(conn, self.identity.task_id, event)
            return items.record(conn, self.identity.task_run_id, self.identity.attempt_id, event)

    def _rule(self, conn: Connection, rule_id: int) -> BusinessRule:
        from etl_craft.core.errors import PermissionDeniedError

        with using(self.definition):
            rules = fetch_business_rules_for_task(conn, self.identity.task_id)
        for rule in rules:
            if rule.business_rule_id == rule_id:
                return rule
        raise PermissionDeniedError(
            f"rule {rule_id}: not an active rule of task {self.identity.task_id}; "
            "report only this attempt's rules"
        )

    def _rule_lock(self, conn: Connection, rule: BusinessRule) -> None:
        if self.identity.attempt_id is None:
            return
        lock = locks.business_rule(rule.business_rule_id, rule.business_rule_name)
        holder = resource_locks.Holder(
            self.identity.holder_id,
            self.identity.owner or "",
            current_actor(),
            self.identity.attempt_id,
        )
        try:
            # Renewing also locks the ownership row through the flag transaction's commit.
            resource_locks.renew(conn, lock.key, holder)
        except StaleTransitionError as error:
            raise StaleTransitionError(
                f"{lock.name}: attempt {self.identity.attempt_id} has no live rule lock; "
                "acquire the rule lock before checking or publishing flags"
            ) from error

    def begin_rule(self, rule_id: int) -> RuleRunBinding:
        """Bind a validated rule under this attempt's task run."""
        with using(self.definition), self.engine.begin() as conn:
            self._assert(conn)
            self._rule_lock(conn, self._rule(conn, rule_id))
            return begin_rule_run(conn, rule_id, self.identity.task_run_id, datetime.now(UTC))

    def rule_keys(self, rule_id: int) -> set[str]:
        """Read flags only for a rule owned by this task."""
        with self.engine.connect() as conn:
            self._assert(conn)
            self._rule(conn, rule_id)
            return fetch_active_rule_keys(conn, rule_id)

    def end_rule(self, ending: RuleEnding) -> None:
        """Commit rule keys and ending together, rejecting another task's run id."""
        from etl_craft.core.errors import PermissionDeniedError
        from etl_craft.engine.queries import statement

        now = datetime.now(UTC)
        with self.engine.begin() as conn:
            self._assert(conn)
            rule = self._rule(conn, ending.rule_id)
            self._rule_lock(conn, rule)
            row = conn.execute(
                statement(conn, "business_rule_run"),
                {"business_rule_id": ending.rule_id, "task_run_id": self.identity.task_run_id},
            ).one_or_none()
            if row is None or row.business_rule_run_id != ending.rule_run_id:
                raise PermissionDeniedError(
                    f"rule run {ending.rule_run_id}: not bound to task run "
                    f"{self.identity.task_run_id}; use the binding returned to this attempt"
                )
            if rule.business_rule_level == BusinessRuleLevel.TABLE:
                if ending.new_keys or ending.passing_keys:
                    raise HandlerError(
                        f"rule {rule.business_rule_name!r}: TABLE publication contains row keys; "
                        "expected only PASSED/OBSERVED/DETAIL; publish a table result"
                    )
                if ending.passed is not None:
                    result = table_result(
                        ending.passed, ending.observed, ending.detail, rule.business_rule_name
                    )
                    if ending.status != result.run_status(rule.business_rule_type):
                        raise HandlerError(
                            f"rule {rule.business_rule_name!r}: TABLE result "
                            f"PASSED={ending.passed}, "
                            f"type={rule.business_rule_type}, status={ending.status}; expected "
                            f"{result.run_status(rule.business_rule_type)}; "
                            "publish the check outcome"
                        )
                elif (
                    ending.status != RunStatus.FAILED
                    or not ending.detail
                    or len(ending.detail) > RULE_TEXT_LIMIT
                ):
                    raise HandlerError(
                        f"rule {rule.business_rule_name!r}: missing TABLE result; "
                        "expected PASSED or a bounded failure DETAIL; report the query outcome"
                    )
                conn.execute(
                    statement(conn, "table_rule_result"),
                    {
                        "business_rule_run_id": ending.rule_run_id,
                        "passed": ending.passed,
                        "observed": ending.observed,
                        "detail": ending.detail,
                    },
                )
            elif any(
                value is not None for value in (ending.passed, ending.observed, ending.detail)
            ):
                raise HandlerError(
                    f"rule {rule.business_rule_name!r}: ROW publication contains TABLE fields; "
                    "expected row keys; publish the row-rule result"
                )
            if ending.status == RunStatus.SUCCESS:
                flag_rule_keys(conn, rule, ending.rule_run_id, ending.new_keys, now)
                clear_rule_keys(conn, ending.rule_id, ending.passing_keys, now)
            finish_rule_run(conn, ending.rule_run_id, ending.status, now)
