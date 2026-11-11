"""Provider logout addresses are discovered, never taken from an untrusted return URL."""

from urllib.parse import urlencode

from etl_craft.core.enums import ActionName
from etl_craft.core.errors import PermissionDeniedError
from etl_craft.services import oidc
from etl_craft.services.operations.browser_paths import public_origin
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.recording import record_refusal
from etl_craft.services.operations.sessions import SignOutResult


def provider_sign_out(ctx: OperationContext, requested: str | None) -> SignOutResult:
    """Return an HTTPS provider redirect after the shared operation revoked the local session."""
    if requested is not None:
        origin = public_origin(ctx.config)
        if requested not in (origin, origin + "/"):
            error = PermissionDeniedError(
                f"post_logout_redirect_uri differs from the public origin {origin}; "
                "omit it or use the configured public origin"
            )
            record_refusal(ctx, ActionName.LOGOUT, {}, error)
            raise error
    if not ctx.config.auth.oidc_issuer:
        return SignOutResult(
            "Signed out of etl-craft; no provider is configured, so sign-out is local."
        )
    _, client, metadata = oidc.client_metadata(ctx.config.auth)
    endpoint = metadata.get("end_session_endpoint")
    if endpoint is None:
        return SignOutResult(
            "Signed out of etl-craft; the provider has no end-session endpoint, "
            "so provider sign-out stays local."
        )
    endpoint = oidc.https_endpoint(endpoint)
    params = {"post_logout_redirect_uri": public_origin(ctx.config), "client_id": client}
    address = endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)
    return SignOutResult(
        "Signed out of etl-craft; continue to the provider to end its session.", address
    )
