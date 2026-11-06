"""Serve the generated catalog site's files to the browser interface's frame, byte for byte."""

from dataclasses import replace

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from etl_craft.api import browser_sessions as browser
from etl_craft.core.enums import ActionName
from etl_craft.core.errors import PermissionDeniedError
from etl_craft.services.operations.actions import invoke
from etl_craft.services.operations.catalog_pages import CatalogInput, CatalogPage
from etl_craft.services.operations.context import OperationContext


def add_catalog_files(app: FastAPI, ctx: OperationContext) -> None:
    """Mount the file route; the catalog's relative links need a path-shaped address."""

    @app.get("/ui/projects/{project}/catalog/files/{path:path}", include_in_schema=False)
    def catalog_file(request: Request, path: str) -> Response:
        caller = replace(
            browser.cookie_context(ctx, request),
            project=request.path_params["project"],
            project_id=None,
        )
        raw = request.scope.get("raw_path", b"")
        if b"%" in raw:
            raise PermissionDeniedError(
                "catalog path contains encoded characters; expected a literal relative "
                "path; open the catalog index"
            )
        page = invoke(caller, ActionName.CATALOG_PAGE, CatalogInput(path=path))
        assert isinstance(page, CatalogPage)
        return StreamingResponse(
            page,
            media_type=page.content_type,
            headers={"X-Content-Type-Options": "nosniff"},
            background=BackgroundTask(page.close),
        )
