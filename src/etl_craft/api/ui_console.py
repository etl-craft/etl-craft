"""The command console's routes: type an etl-craft command line, see what the CLI would print.

The CLI's runner parses and runs the line as the signed-in person (see ``cli.console``); this
module only authenticates the browser request, checks its CSRF proof and returns the text.
"""

from dataclasses import replace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from etl_craft.api import browser_sessions as browser
from etl_craft.api.console import Console
from etl_craft.core.errors import UsageError
from etl_craft.services.operations.context import OperationContext

MAX_LINE = 4096


def add_console_routes(app: FastAPI, ctx: OperationContext, console: Console | None) -> None:
    """Mount the console's command list and run route."""

    @app.get("/ui/projects/{project}/console/commands", include_in_schema=False)
    def commands(request: Request, project: str) -> Response:
        """List the commands, with their flags, that the signed-in person may type here."""
        caller = replace(browser.cookie_context(ctx, request), project=project, project_id=None)
        listed = {} if console is None else console.commands(caller)
        return JSONResponse(
            {
                "available": console is not None,
                "commands": {name: list(flags) for name, flags in listed.items()},
            }
        )

    @app.post("/ui/projects/{project}/console", include_in_schema=False)
    async def run(request: Request, project: str) -> Response:
        caller = browser.cookie_context(ctx, request)
        caller = replace(caller, project=project, project_id=None)
        body = await request.json()
        line = body.get("line") if isinstance(body, dict) else None
        if console is None:
            raise UsageError("the console runs only in `etl-craft ui` and `etl-craft controller`")
        if not isinstance(line, str) or len(line) > MAX_LINE:
            raise UsageError(f"line: expected text of at most {MAX_LINE} characters")
        actions = console.actions(line)
        if actions:
            browser.csrf_check(caller, actions[0], request, request.headers.get("X-CSRF-Token", ""))
        result = await run_in_threadpool(console.run, caller, line)
        return JSONResponse(
            {"exit_code": result.exit_code, "output": result.output, "error": result.error}
        )
