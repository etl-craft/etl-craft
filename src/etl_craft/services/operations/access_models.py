"""Access command contracts shared by the CLI, the HTTP API and the UI.

Every binding gives WHO (an account, a group, or every account with an audience's deployment
role) WHAT (a role, built-in CAN_* or custom, or one action) WHERE (the deployment, every project
of one environment type, or one project, optionally narrowed to a pipeline or a tag).
"""

from dataclasses import dataclass
from typing import ClassVar

from etl_craft.core.enums_access import AccessChange, BindingScope, Permission
from etl_craft.services.operations.requests import Request, optional_text


@dataclass(frozen=True, kw_only=True)
class AccessFilter(Request):
    """Where to look, and optional exact identity filters."""

    project: str | None = None
    environment: str | None = None
    deployment: bool = False
    group: str | None = None
    account: str | None = None
    audience: str | None = None
    pipeline: str | None = None
    tag: str | None = None

    def __post_init__(self) -> None:
        """Refuse explicitly blank selectors instead of storing an invalid binding."""
        for name in ("project", "environment", "group", "account", "audience", "pipeline", "tag"):
            optional_text(name, getattr(self, name))

    @property
    def reaches_beyond_project(self) -> bool:
        """Deployment and environment bindings are not owned by one project."""
        return self.deployment or self.environment is not None


@dataclass(frozen=True, kw_only=True)
class AccessWrite(AccessFilter):
    """One binding to grant or revoke."""

    reason: str
    role: str | None = None
    action: str | None = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Require optional role and action inputs to be nonblank when supplied."""
        super().__post_init__()
        optional_text("role", self.role)
        optional_text("action", self.action)


@dataclass(frozen=True)
class Binding:
    """One binding, retained after it is revoked."""

    scope: BindingScope
    project: str | None
    environment: str | None
    group: str | None
    account: str | None
    audience: str | None
    pipeline: str | None
    tag: str | None
    role: str | None
    action: str | None
    active_flag: str


@dataclass(frozen=True)
class Change:
    """What a grant or revoke did, including the built-in level it replaced."""

    binding: Binding
    previous_role: str | None
    change: AccessChange


@dataclass(frozen=True)
class AccessView:
    """Access administration output shared by the CLI and API."""

    SCHEMA: ClassVar[str] = "etl-craft/access/2"
    bindings: tuple[Binding, ...] = ()
    effective: tuple[tuple[str, str | None, tuple[str, ...]], ...] = ()
    project_level: Permission | None = None
    project_sources: tuple[str, ...] = ()
    change: Change | None = None
    dry_run: bool = False
