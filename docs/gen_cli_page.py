"""Generate reference/cli.md from the command line's own parser, so it matches the release.

Run by the mkdocs-gen-files plugin during `mkdocs build`; the page exists only in the build.
"""

import argparse
import os

import mkdocs_gen_files

from etl_craft.cli import build_parser

# argparse wraps help text to the terminal width; a fixed width keeps the page stable.
os.environ["COLUMNS"] = "100"
parser = build_parser()
sections = [
    "# Command line\n",
    "Every command accepts the global options, before or after the command name. Results are "
    "written to standard output; errors (`error: ...`) and log records go to standard error. "
    "The [exit codes](exit-codes.md) page lists what each exit status means.\n",
    "Project-scoped text commands print `project · environment · API URL` (or `local`) on stderr. "
    "PROD displays PRODUCTION; other types retain the optional environment name. JSON adds "
    "an `environment` object with `type` and `name`, without a context line. Deployment-wide "
    "commands have no project banner. Login/whoami include the selected environment, "
    "including while a temporary password requires replacement.\n",
    "Production state-changing CLI actions require typing the exact project code at a terminal. "
    "Without a terminal they refuse unless `--yes` is supplied; automation must pass `--yes` "
    "explicitly. Non-production commands never prompt for environment confirmation. This CLI "
    "presentation check does not change API authorization.\n",
    "When `CI` is set, production confirmation never prompts, even with a terminal; pass "
    "`--yes`. For command groups put it before the group, for example "
    "`etl-craft --yes config apply`.\n",
    "A legacy `migrate` reports `environment unknown (Engine DB predates environment metadata)` "
    "alongside the credential-free Engine DB identity. Its JSON has `environment: null` and "
    "`environment_reason`. Packaged migrations run first; any PROD project migrations confirm "
    "before their first write. Later invocations use the normal environment context.\n",
    f"```text\n{parser.format_help()}```\n",
]


def command_sections(parser, prefix=""):
    """Render help for every parser under its full command path."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                command = f"{prefix} {name}".strip()
                yield f"## `{command}`\n"
                yield f"```text\n{subparser.format_help()}```\n"
                yield from command_sections(subparser, command)


sections.extend(command_sections(parser))

with mkdocs_gen_files.open("reference/cli.md", "w", encoding="utf-8") as handle:
    handle.write("\n".join(sections))
mkdocs_gen_files.set_edit_path("reference/cli.md", "../src/etl_craft/cli/__init__.py")
