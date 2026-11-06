"""HTTP-only fixed-lifetime browser credentials and same-origin change requests."""

import hmac
import re
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from etl_craft.core.enums import ActionName, Transport
from etl_craft.core.errors import PermissionDeniedError, UsageError
from etl_craft.core.text import sha256_hex
from etl_craft.core.time import as_utc
from etl_craft.services.operations.context import OperationContext
from etl_craft.services.operations.identity import authenticated_context
from etl_craft.services.operations.recording import record_refusal
from etl_craft.services.operations.sessions import Session, SsoPoll
from etl_craft.services.operations.tokens import authenticate

SESSION = "__Host-etl-craft-session"
CSRF = "__Host-etl-craft-csrf"
BACKGROUND = "X-ETL-Background"


def browser_request(request: Request) -> bool:
    """Bearer callers retain the JSON protocol without cookie authority."""
    return not request.headers.get("authorization") and (
        request.cookies.get(SESSION, "") != "" or request.headers.get("X-CSRF-Token") is not None
    )


def return_path(value: str) -> str:
    """Accept a same-site absolute path, refusing host, scheme and encoded authority tricks."""
    decoded = unquote(value)
    try:
        parts = urlsplit(decoded)
    except ValueError as error:
        raise UsageError("return_to is malformed; expected a same-site path; open /ui") from error
    if (
        len(value) > 4096
        or not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or parts.scheme
        or parts.netloc
        or unquote(decoded) != decoded
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
    ):
        raise UsageError(f"return_to={value!r}; expected a same-site path such as /ui; open /ui")
    return value


def has_challenge(request: Request) -> bool:
    """Whether the request carries a well-formed challenge cookie."""
    return re.fullmatch(r"[A-Za-z0-9_-]{43}", request.cookies.get(CSRF, "")) is not None


def csrf_value(request: Request) -> str:
    """Keep an existing well-formed challenge; never echo arbitrary cookie text."""
    return request.cookies[CSRF] if has_challenge(request) else secrets.token_urlsafe(32)


def csrf_check(ctx: OperationContext, action: ActionName, request: Request, supplied: str) -> None:
    """Browser changes require the host-only double-submit challenge and a same-site origin."""
    expected = request.cookies.get(CSRF, "")
    origin = request.headers.get("origin")
    allowed = True
    if origin:
        try:
            parsed = urlsplit(origin)
            allowed = (
                parsed.scheme in ("http", "https")
                and parsed.netloc.lower() == request.headers.get("host", "").lower()
            )
        except ValueError:
            allowed = False
    if (
        re.fullmatch(r"[A-Za-z0-9_-]{43}", expected) is None
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", supplied) is None
        or not hmac.compare_digest(expected, supplied)
        or not allowed
    ):
        error = PermissionDeniedError(
            "browser change refused: CSRF proof or origin is invalid; expected this page's "
            "current challenge; reload the page and submit from this server"
        )
        record_refusal(ctx, action, {"security": "CSRF", "path": request.url.path}, error)
        raise error


def is_background(request: Request) -> bool:
    """Whether the page marked this request as a refresh nobody asked for."""
    return request.headers.get(BACKGROUND) == "1"


def cookie_context(ctx: OperationContext, request: Request) -> OperationContext:
    """Authenticate the same opaque token used by the API; pages never prove identity themselves."""
    token = request.cookies.get(SESSION, "")
    identity = authenticate(ctx, token, background=is_background(request)) if token else None
    if identity is None:
        raise HTTPException(401, "Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    return replace(
        authenticated_context(ctx, identity),
        transport=Transport.HTTP,
        browser_session=True,
        credential_digest=sha256_hex(token.encode()),
    )


def challenge(response: Response, value: str, hours: int) -> None:
    """Challenge cookies are host-only, secure and unreadable to scripts."""
    response.set_cookie(
        CSRF, value, max_age=hours * 3600, secure=True, httponly=True, samesite="lax", path="/"
    )


def signed_out(response: Response) -> None:
    """Remove shared cookies; token revocation invalidates every tab."""
    for name in (SESSION, CSRF):
        response.delete_cookie(name, secure=True, httponly=True, samesite="lax", path="/")
    response.headers["X-ETL-Session"] = "signed-out"


def browser_answer(
    ctx: OperationContext,
    action: ActionName,
    request: Request,
    result: object,
    destination: str,
) -> Response | None:
    """Render cookie sessions without placing token values in HTML or JSON."""
    if isinstance(result, SsoPoll) and result.session is not None:
        result = result.session
    if isinstance(result, Session):
        target = "/ui/password" if result.must_change_password else return_path(destination)
        response: Response = JSONResponse({"redirect": target})
        assert result.metadata.expires_at is not None
        end = as_utc(result.metadata.expires_at)
        response.set_cookie(
            SESSION,
            result.access_token,
            max_age=max(0, int((end - datetime.now(UTC)).total_seconds())),
            expires=end,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
        )
        challenge(response, secrets.token_urlsafe(32), ctx.config.auth.session_hours)
        response.headers["X-ETL-Session"] = "signed-in"
        return response
    if isinstance(result, SsoPoll):
        return JSONResponse({"interval": result.interval})
    if action in (ActionName.LOGOUT, ActionName.PASSWORD_CHANGE):
        response = JSONResponse({"message": getattr(result, "message", "Signed out.")})
        signed_out(response)
        return response
    return None
