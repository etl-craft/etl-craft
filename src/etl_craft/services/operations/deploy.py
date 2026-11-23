"""``etl-craft deploy``: publish, apply config, load seeds and refresh pipelines, in that order.

With ``Artifacts.Store`` set, the caller uploads the project's files; deploy publishes them as a
bundle and every later step reads that publication. Without a store, every step reads the
project folder on this host, so the API refuses a deploy there. Config files are applied when
the project has ``config/`` (a project kept in migrations has none); seed tables load when it
has ``seeds/``; every pipeline is refreshed. The first failing step stops the rest.

``plan`` runs the same steps without writing: the upload is checked and unpacked but not
published, the config changes are validated and rolled back, and the seed tables are listed.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import ClassVar

from etl_craft.config import ConnectorConfig
from etl_craft.config.project import project_config
from etl_craft.core.enums import ActionName, ApiRole, RunStatus, Transport
from etl_craft.core.enums_uploads import SeedStatus
from etl_craft.core.errors import UsageError
from etl_craft.engine.bundles import Bundle
from etl_craft.engine.project_files import decode_files
from etl_craft.services import config_files
from etl_craft.services.config_files import ConfigSync
from etl_craft.services.operations import bundles
from etl_craft.services.operations.config_files import sync_folder
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.requests import Request
from etl_craft.services.operations.seeds import SeedLoad, apply_seeds
from etl_craft.services.refresh_models import PipelineRefresh, RefreshResults
from etl_craft.services.seeds import discover

CONNECTOR = "craft-connector.yml"


@dataclass(frozen=True, kw_only=True)
class DeployInput(Request):
    """The project's files, sent only when ``Artifacts.Store`` is set, and whether to plan."""

    MAX_BODY_BYTES: ClassVar[int] = bundles.PublishBundle.MAX_BODY_BYTES
    files: dict[str, str] = field(default_factory=dict, metadata={"audit": False})
    plan: bool = False


@dataclass(frozen=True)
class Deployment:
    """Each step's outcome; a step after a failed one did not run and stays empty."""

    SCHEMA: ClassVar[str] = "etl-craft/deploy/1"
    plan: bool
    bundle_id: str | None
    config: ConfigSync | None
    """The config files' merge, or ``None`` for a project without ``config/``."""
    seeds: tuple[str, ...] = ()
    """The seed tables the project declares, loaded or (in a plan) to be loaded."""
    seed_loads: tuple[SeedLoad, ...] = ()
    refreshes: tuple[PipelineRefresh, ...] = ()

    @property
    def failed(self) -> bool:
        """Whether a step failed, so the steps after it did not run."""
        return (
            (self.config is not None and self.config.failed)
            or any(load.status == SeedStatus.FAILED for load in self.seed_loads)
            or any(result.status == RunStatus.FAILED for result in self.refreshes)
        )


def required_role(ctx: OperationContext, request: object) -> ApiRole:
    """Require an admin only when the publication changes the approved connection contract."""
    assert isinstance(request, DeployInput)
    if not request.files or request.plan:
        return ApiRole.DEVELOPER
    return bundles.required_role(ctx, bundles.PublishBundle(files=request.files))


def deploy(ctx: OperationContext, request: DeployInput) -> Deployment:
    """Run the steps in order and stop at the first failure."""
    store = bool(ctx.config.artifacts.store)
    _check_source(ctx, request, store=store)
    if not store:
        return _steps(ctx, request, ctx.config, None)
    if request.plan:
        bundles.check_upload(ctx, bundles.PublishBundle(files=request.files))
        with tempfile.TemporaryDirectory(prefix="etl-craft-deploy-") as scratch:
            root = _unpack(request.files, Path(scratch))
            return _steps(ctx, request, project_config(ctx.config, root / CONNECTOR), None)
    published = bundles.publish(ctx, bundles.PublishBundle(files=request.files))
    with ctx.engine.connect() as conn:
        root = Bundle.select(conn, ctx.project_id, published.bundle_id).materialize(ctx.config)
    config = project_config(ctx.config, root / CONNECTOR)
    return _steps(ctx, request, config, published.bundle_id)


def _check_source(ctx: OperationContext, request: DeployInput, *, store: bool) -> None:
    """Refuse files the deployment would not read, and a host folder the caller cannot see."""
    if store and not request.files:
        raise UsageError(
            f"project {ctx.project!r}: deploy without files, but Artifacts.Store is set; expected "
            "the project's files to publish; run `etl-craft deploy` from the project folder"
        )
    if not store and request.files:
        raise UsageError(
            f"project {ctx.project!r}: deploy sent {len(request.files)} files, but this "
            "deployment has no Artifacts.Store, so it reads its own project folder; set "
            "Artifacts.Store to publish uploaded files, or deploy on the controller's host"
        )
    if not store and ctx.transport == Transport.HTTP:
        raise UsageError(
            f"project {ctx.project!r}: deploy over the API needs Artifacts.Store, since without "
            "one deploy reads the project folder on the server's host; configure Artifacts.Store"
        )


def _unpack(files: dict[str, str], root: Path) -> Path:
    """Write the checked upload to ``root``, as a publication would materialize it."""
    _, content = decode_files(files)
    for name, data in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def _steps(
    ctx: OperationContext, request: DeployInput, config: ConnectorConfig, bundle_id: str | None
) -> Deployment:
    folder = config_files.config_directory(config)
    synced = (
        sync_folder(ctx, folder, config, bundle_id, apply=not request.plan)
        if folder.is_dir()
        else None
    )
    done = Deployment(request.plan, bundle_id, synced)
    seeds = discover(config)
    done = replace(done, seeds=tuple(seed.target for seed in seeds))
    if done.failed or request.plan:
        return done
    done = replace(done, seed_loads=apply_seeds(replace(ctx, config=config), seeds).loads)
    if done.failed:
        return done
    return replace(done, refreshes=_refresh(ctx, bundle_id))


def _refresh(ctx: OperationContext, bundle_id: str | None) -> tuple[PipelineRefresh, ...]:
    from etl_craft.services.operations.actions import invoke
    from etl_craft.services.operations.pipeline_refresh import InternalRefresh

    checked = invoke(ctx, ActionName.PIPELINE_REFRESH, InternalRefresh(bundle=bundle_id))
    assert isinstance(checked, RefreshResults)
    return checked.refreshes
