"""Serve the built browser interface under ``/app``; it calls only ``/api/v1`` as the session."""

import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from etl_craft.api import browser_sessions as browser
from etl_craft.core.errors import ResourceNotFoundError
from etl_craft.services.operations.context import OperationContext

BUNDLE = Path(__file__).parent / "spa"
CSRF_SLOT = "__CSRF__"


def _document() -> str:
    """Read the built shell; a missing bundle is an installation fault with a remedy."""
    shell = BUNDLE / "index.html"
    if not shell.is_file():
        raise ResourceNotFoundError(
            f"{shell}: the browser interface bundle is missing from this installation; "
            "reinstall etl-craft from its wheel, or in a source checkout run `make ui-build`"
        )
    return shell.read_text(encoding="utf-8")


def add_spa_pages(app: FastAPI, ctx: OperationContext) -> None:
    """Mount the built assets, and the shell for every ``/app`` path the router resolves."""
    app.mount("/app/assets", StaticFiles(directory=BUNDLE / "assets", check_dir=False), name="spa")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    def shell(request: Request, path: str = "") -> Response:
        public = path.rstrip("/") == "signin"
        try:
            browser.cookie_context(ctx, request)
        except HTTPException:
            if not public:
                back = request.url.path + ("?" + request.url.query if request.url.query else "")
                return RedirectResponse("/app/signin?return_to=" + quote(back, safe=""), 303)
        else:
            if public:
                back = request.query_params.get("return_to", "/app")
                return RedirectResponse(browser.return_path(back), 303)
        fresh = None if browser.has_challenge(request) else secrets.token_urlsafe(32)
        token = fresh or request.cookies[browser.CSRF]
        response = HTMLResponse(_document().replace(CSRF_SLOT, token))
        if fresh is not None:
            browser.challenge(response, fresh, ctx.config.auth.session_hours)
        return response
