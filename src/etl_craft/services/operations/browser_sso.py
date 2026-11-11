"""Browser authorization-code sign-in, bound to an expiring, single-use signed cookie."""

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field, replace
from typing import ClassVar
from urllib.parse import urlencode

from etl_craft.config.resolve import resolve_named_secret
from etl_craft.core.actor import SYSTEM_ACTOR
from etl_craft.core.enums import ActionName, ActionOutcome
from etl_craft.core.errors import ConfigurationError, EtlCraftError, PermissionDeniedError
from etl_craft.core.text import sha256_hex
from etl_craft.engine import locks
from etl_craft.engine.queries import statement
from etl_craft.services import oidc
from etl_craft.services.operations.browser_paths import public_origin, return_path
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.recording import record_refusal, recorded
from etl_craft.services.operations.requests import Request
from etl_craft.services.operations.schema_status import require_current_schema
from etl_craft.services.operations.sessions import Session, sign_in_subject

LIFETIME = 300
CALLBACK = "/ui/signin/callback"


@dataclass(frozen=True)
class BrowserStart:
    """The provider address and the cookie proof; only the address goes into JSON."""

    SCHEMA: ClassVar[str] = "etl-craft/browser-sso-start/1"
    authorization_url: str
    cookie: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class StartInput(Request):
    """The same-site page to return to after sign-in."""

    return_to: str = "/ui"

    def __post_init__(self) -> None:
        """Refuse any external return address before contacting the issuer."""
        return_path(self.return_to)


@dataclass(frozen=True, kw_only=True)
class CallbackInput(Request):
    """The provider response and the proof read from the browser's HTTP-only cookie."""

    code: str = field(metadata={"audit": False})
    state: str = field(metadata={"audit": False})
    cookie: str = field(default="", metadata={"audit": False})


@dataclass(frozen=True)
class BrowserFinish:
    """The existing session and its validated same-site return address."""

    SCHEMA: ClassVar[str] = "etl-craft/browser-sso-finish/1"
    session: Session
    destination: str


def signing_key(ctx: OperationContext) -> str:
    """Resolve the configured variable only when browser sign-in is used."""
    name = ctx.config.auth.browser_state_secret
    if not name:
        raise ConfigurationError(
            "Browser sign-in needs Auth.Browser_state_secret; see the security guide."
        )
    key = resolve_named_secret(ctx.config, name)
    if len(key.encode()) < 32:
        raise ConfigurationError(
            f"Auth.Browser_state_secret variable {name}: expected at least 32 bytes; "
            "set a random secret of at least 32 bytes in the configured Secrets provider"
        )
    return key


def redirect_address(ctx: OperationContext) -> str:
    """Use the configured deployment URL, never the request authority."""
    return public_origin(ctx.config) + CALLBACK


def start(ctx: OperationContext, request: StartInput) -> BrowserStart:
    """Issue an authorization URL with PKCE and a signed five-minute browser binding."""
    import jwt

    if not ctx.browser_session:
        raise PermissionDeniedError("browser SSO requires the browser session; open /ui/signin")
    require_current_schema(ctx)
    key = signing_key(ctx)
    redirect = redirect_address(ctx)
    _, client, metadata = oidc.client_metadata(ctx.config.auth)
    endpoint = metadata.get("authorization_endpoint")
    # Discovery endpoints use the same HTTPS validation as device authorization.
    from etl_craft.services.oidc import https_endpoint

    endpoint = https_endpoint(endpoint)
    state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    with recorded(
        ctx, ActionName.LOGIN, {"browser_flow": sha256_hex(state.encode()), "phase": "issued"}
    ) as issued:
        assert issued.action_id is not None
        issued_id = issued.action_id
    proof = jwt.encode(
        {
            "issued_id": issued_id,
            "state": state,
            "verifier": verifier,
            "nonce": nonce,
            "exp": int(time.time()) + LIFETIME,
            "return_to": request.return_to,
            "redirect_uri": redirect,
        },
        key,
        algorithm="HS256",
    )
    params = {
        "response_type": "code",
        "scope": "openid email profile",
        "client_id": client,
        "redirect_uri": redirect,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return BrowserStart(endpoint + ("&" if "?" in endpoint else "?") + urlencode(params), proof)


def _consume(ctx: OperationContext, state: str, issued_id: int) -> None:
    """Commit consumption before exchange; crashes and other replicas cannot replay it."""
    digest = sha256_hex(state.encode())
    with locks.ACCOUNTS.hold(ctx.engine, wait_seconds=30):
        with ctx.engine.connect() as conn:
            consumed = conn.execute(
                statement(conn, "browser_flow_consumed"),
                {
                    "actor": SYSTEM_ACTOR.name,
                    "issued_id": issued_id,
                    "digest": digest,
                    "flow": f'%"browser_flow": "{digest}"%',
                    "phase": '%"phase": "consumed"%',
                },
            ).scalar_one()
        if consumed:
            raise PermissionDeniedError("browser SSO state was already used; start sign-in again")
        marker = replace(ctx, actor=SYSTEM_ACTOR)
        with recorded(
            marker,
            ActionName.LOGIN,
            {"browser_flow": digest, "phase": "consumed"},
            on_completion=True,
        ) as audit:
            audit.outcome = ActionOutcome.SUCCESS
            audit.record()


def _identity(ctx: OperationContext, code: str, proof: dict[str, object]) -> oidc.IdentityClaims:
    """Exchange the code over TLS and require an issuer-signed token with our nonce."""
    import jwt

    issuer, client, metadata = oidc.client_metadata(ctx.config.auth)
    response = oidc.request_json(
        str(metadata["token_endpoint"]),
        {
            "grant_type": "authorization_code",
            "client_id": client,
            "code": code,
            "redirect_uri": str(proof["redirect_uri"]),
            "code_verifier": str(proof["verifier"]),
        },
    )
    token = response.get("id_token")
    if not isinstance(token, str):
        raise PermissionDeniedError("browser SSO code exchange refused; start sign-in again")
    keys = oidc.request_json(oidc.https_endpoint(metadata.get("jwks_uri"))).get("keys", [])
    header = jwt.get_unverified_header(token)
    if not isinstance(keys, list):
        raise ConfigurationError("OIDC JWKS keys: expected a list; correct the issuer metadata")
    matching = [
        k
        for k in keys
        if isinstance(k, dict)
        and k.get("kid") == header.get("kid")
        and k.get("kty") == "RSA"
        and k.get("use", "sig") == "sig"
        and k.get("alg", "RS256") == "RS256"
    ]
    if len(matching) != 1:
        raise PermissionDeniedError("browser SSO signing key is unknown; start sign-in again")
    claims = jwt.decode(
        token,
        jwt.PyJWK.from_dict(matching[0]).key,
        algorithms=["RS256"],
        audience=client,
        issuer=issuer,
        leeway=oidc.CLOCK_LEEWAY_SECONDS,
        options={"require": ["exp", "iat", "sub", "nonce", "iss", "aud"]},
    )
    if not hmac.compare_digest(str(claims.get("nonce", "")).encode(), str(proof["nonce"]).encode()):
        raise PermissionDeniedError("browser SSO nonce differs; start sign-in again")
    claims = oidc.token_claims(token, issuer, client, str(proof["nonce"]))
    return oidc.identity_claims(ctx.config.auth, claims)


def callback(ctx: OperationContext, request: CallbackInput) -> BrowserFinish:
    """Refuse missing, expired, mismatched or replayed proof and audit every refusal."""
    import jwt

    require_current_schema(ctx)
    try:
        if not ctx.browser_session:
            raise PermissionDeniedError("browser SSO requires the browser session; open /ui/signin")
        proof = jwt.decode(
            request.cookie,
            signing_key(ctx),
            algorithms=["HS256"],
            options={
                "require": [
                    "state",
                    "verifier",
                    "nonce",
                    "exp",
                    "redirect_uri",
                    "return_to",
                    "issued_id",
                ]
            },
        )
        if not request.state or not hmac.compare_digest(
            request.state.encode(), str(proof["state"]).encode()
        ):
            raise PermissionDeniedError("browser SSO state differs; start sign-in again")
        if proof["redirect_uri"] != redirect_address(ctx):
            raise PermissionDeniedError("browser SSO public address changed; start sign-in again")
        _consume(ctx, request.state, int(proof["issued_id"]))
        claims = _identity(ctx, request.code, proof)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        error = PermissionDeniedError(
            "browser SSO proof or ID token is invalid or expired; start sign-in again"
        )
        record_refusal(ctx, ActionName.LOGIN, {"method": "browser"}, error)
        raise error from None
    except EtlCraftError as error:
        record_refusal(ctx, ActionName.LOGIN, {"method": "browser"}, error)
        raise
    return BrowserFinish(
        sign_in_subject(replace(ctx, browser_session=True), claims), str(proof["return_to"])
    )
