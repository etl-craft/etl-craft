"""Apply the deployment's immutable reference seeds without inventing a pipeline run."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from etl_craft.config.project import project_config
from etl_craft.config.resolve import source_values
from etl_craft.config.targets import active_catalog
from etl_craft.core.actor import acting_as
from etl_craft.core.definitions import Definition
from etl_craft.core.enums import SqlAction
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.core.errors import ConfigurationError, EtlCraftError, HandlerError
from etl_craft.core.faults import fault_point
from etl_craft.core.text import is_secret_name, mask_arguments, pipe_list
from etl_craft.core.time import as_utc
from etl_craft.engine import locks
from etl_craft.engine.bundles import Bundle
from etl_craft.engine.queries import statement
from etl_craft.engine.repository.hash_versions import clear_hash_version, save_hash_version
from etl_craft.engine.repository.normalization import object_identity
from etl_craft.engine.repository.tasks import admitted_parameters, fetch_all_task_parameters
from etl_craft.handlers.resources import LocalLocker
from etl_craft.handlers.sql.seed import replace_seed
from etl_craft.handlers.sql.session import Session
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import NoInput
from etl_craft.services.seeds import Seed, cast_rows, discover
from etl_craft.warehouse.connection import open_warehouse, warehouse_dialect


@dataclass(frozen=True)
class SeedLoad:
    """One table's immutable audit identity and outcome."""

    table: str
    seed_load_id: str
    status: SeedStatus
    message: str


@dataclass(frozen=True)
class SeedLoads:
    """The completed per-table outcomes, including independent failures."""

    SCHEMA: ClassVar[str] = "etl-craft/seed-loads/1"
    loads: tuple[SeedLoad, ...]


def apply(ctx: OperationContext, request: NoInput) -> SeedLoads:
    """Read once from the pinned publication; serialize each decision with target writers."""
    with ctx.engine.connect() as conn:
        identity = conn.execute(statement(conn, "bundle_latest")).scalar_one_or_none()
        if identity is None:
            raise ConfigurationError(
                f"project {ctx.project!r}: bundle=missing; expected an approved publication; "
                "run etl-craft bundle publish before seed apply"
            )
        bundle = Bundle.load(conn, identity)
    config = project_config(ctx.config, bundle.materialize(ctx.config) / "craft-connector.yml")
    ctx = replace(ctx, config=config)
    with acting_as(ctx.actor):
        return SeedLoads(tuple(_apply_table(ctx, seed) for seed in discover(config)))


def _apply_table(ctx: OperationContext, seed: Seed) -> SeedLoad:
    identity = str(uuid4())
    status, message = SeedStatus.FAILED, ""
    merge = None
    try:
        with locks.target(seed.target, active_catalog(ctx.config)).hold(
            LocalLocker(ctx.engine, ctx.config)
        ):
            with ctx.engine.connect() as conn:
                locked = _locked(conn, ctx, seed)
                previous = conn.execute(
                    statement(conn, "seed_load_latest"), _parameters(seed)
                ).one_or_none()
            if locked is not None:
                status, message = SeedStatus.LOCKED, locked
            elif (
                previous is not None
                and previous.status in (SeedStatus.LOADED, SeedStatus.UNCHANGED)
                and previous.content_sha256 == seed.sha256
            ):
                status, message = SeedStatus.UNCHANGED, f"{seed.target}: UNCHANGED"
            else:
                merge = _load(ctx, seed)
                status, message = SeedStatus.LOADED, f"{seed.target}: LOADED"
            _record(ctx, seed, SeedLoad(seed.target, identity, status, message), merge)
    except (EtlCraftError, SQLAlchemyError, OSError) as error:
        detail = (str(error) or type(error).__name__).splitlines()[0]
        failure = HandlerError(
            f"{seed.target}, seed load {identity}: value=load failed ({detail}); "
            "expected valid seed files and a writable warehouse target; correct the files "
            "or restore the warehouse connection, publish the corrected bundle and retry seed apply"
        )
        message = str(mask_arguments({"message": str(failure)})["message"])
        profiles = (ctx.config.engine, ctx.config.warehouse, ctx.config.email)
        references = {profile.secret_var for profile in profiles if profile is not None}
        for name, secret in source_values(ctx.config.source).items():
            if secret and (name in references or is_secret_name(name)):
                message = message.replace(secret, "[REDACTED]")
        _record(ctx, seed, SeedLoad(seed.target, identity, SeedStatus.FAILED, message))
        status = SeedStatus.FAILED
    return SeedLoad(seed.target, identity, status, message)


def _parameters(seed: Seed) -> dict[str, object]:
    return dict(zip(("catalog_name", "schema_name", "table_name"), seed.identity, strict=True))


def _record(ctx: OperationContext, seed: Seed, result: SeedLoad, merge: bool | None = None) -> None:
    """Commit the outcome and any post-warehouse hash publication together."""
    with ctx.engine.begin() as conn:
        if merge is not None:
            if merge:
                save_hash_version(conn, seed.target, 2)
            else:
                clear_hash_version(conn, seed.target)
        conn.execute(
            statement(conn, "seed_load_insert"),
            {
                **_parameters(seed),
                "project_id": ctx.project_id,
                "seed_load_id": result.seed_load_id,
                "content_sha256": seed.sha256,
                "status": result.status,
                "error_message": result.message if result.status == SeedStatus.FAILED else None,
                "actor": ctx.actor.name,
                "now": datetime.now(UTC),
            },
        )
        if merge is not None:
            fault_point("seed.before_audit_commit")


def _locked(conn: Connection, ctx: OperationContext, seed: Seed) -> str | None:
    for query in ("seed_upload_runs", "seed_reopened_runs"):
        after_ended, after_run = datetime.min.replace(tzinfo=UTC), 0
        while True:
            uploads = conn.execute(
                statement(conn, query),
                {"after_ended": after_ended, "after_run_id": after_run, "limit": 100},
            ).all()
            if not uploads:
                break
            for run in uploads:
                if run.snapshot is None:
                    raise ConfigurationError(
                        f"run {run.run_id}: snapshot=missing; "
                        "expected the upload run's pinned metadata; "
                        "restore its metadata snapshot before seed apply"
                    )
                if run.bundle_id is None:
                    raise ConfigurationError(
                        f"run {run.run_id}: bundle=missing; expected its pinned warehouse catalog; "
                        "restore the recorded bundle before seed apply"
                    )
                bundle = Bundle.load(conn, run.bundle_id)
                pinned = project_config(
                    ctx.config, bundle.materialize(ctx.config) / "craft-connector.yml"
                )
                language = warehouse_dialect(pinned).sqlglot_dialect
                definition = Definition.read(run.snapshot, run.run_id)
                for task in definition.rows["CFG_TASKS"]:
                    if task["pipeline_id"] != run.pipeline_id:
                        continue
                    params = admitted_parameters(definition, int(str(task["task_id"])))
                    target = params.get("TARGET_OBJECT")
                    if (
                        target
                        and object_identity(target, active_catalog(pinned), language)
                        == seed.identity
                    ):
                        pipeline = definition.row("CFG_PIPELINES", "pipeline_id", run.pipeline_id)[
                            "pipeline_code"
                        ]
                        path = seed.directory.relative_to(ctx.config.project_dir)
                        return (
                            f"{seed.target} is maintained through stewardship since upload "
                            f"{run.upload_id} "
                            f"on {run.uploaded_at} (pipeline {pipeline}); {path} was not applied. "
                            f"Upload changes on the UI's Uploads page for {pipeline}."
                        )
            after_ended, after_run = as_utc(uploads[-1].ended_at), uploads[-1].run_id
    return None


def _merge(ctx: OperationContext, seed: Seed) -> tuple[SqlAction, tuple[str, ...]] | None:
    language = warehouse_dialect(ctx.config).sqlglot_dialect
    with ctx.engine.connect() as conn:
        tasks = fetch_all_task_parameters(conn)
    contracts = set()
    for params in tasks.values():
        target = params.get("TARGET_OBJECT")
        if not target or params.get("SQL_ACTION") not in (
            SqlAction.SCD1_MERGE,
            SqlAction.SCD2_MERGE,
        ):
            continue
        if object_identity(target, active_catalog(ctx.config), language) == seed.identity:
            keys = tuple(c.lower() for c in pipe_list(params.get("MERGE_KEY")))
            compare = tuple(c.lower() for c in pipe_list(params.get("MERGE_COMPARE_COLUMNS")))
            contracts.add((SqlAction(params["SQL_ACTION"]), keys, compare))
    if not contracts:
        return None
    if len(contracts) != 1:
        raise HandlerError(
            f"{seed.target}: value={sorted(contracts)!r}; "
            f"expected one merge contract; align the target's merge tasks"
        )
    action, keys, compare = next(iter(contracts))
    names = {name.lower() for name, _ in seed.columns}
    if keys != seed.keys or not compare or not set(compare) <= names:
        raise HandlerError(
            f"{seed.target}: value=seed keys {seed.keys}, compare {compare}; "
            f"expected merge keys {keys} and declared compare columns; correct columns.csv or "
            f"the merge task"
        )
    return action, compare


def _load(ctx: OperationContext, seed: Seed) -> bool:
    config = ctx.config
    merge = _merge(ctx, seed)
    with open_warehouse(config, LocalLocker(ctx.engine, config)) as warehouse:
        with warehouse.connect() as conn:
            rows = cast_rows(conn, seed)
        with warehouse.begin() as conn:
            session = Session(
                conn,
                warehouse_dialect(config),
                catalog=active_catalog(config),
                action=SqlAction.CREATE_TABLE,
                target_object=seed.target,
                task_run_id=0,
                params={},
            )
            try:
                replace_seed(session, seed.columns, rows, merge, ctx.actor.name)
            finally:
                session.sweep()
        fault_point("seed.after_warehouse_commit")
    return merge is not None
