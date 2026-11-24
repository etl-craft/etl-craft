"""Generate one API reference page per public module under src/etl_craft, and their navigation.

Run by the mkdocs-gen-files plugin during `mkdocs build`; the pages exist only in the build.
"""

import ast
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Older release tags name the guide ingestion-scripts.md, and this renderer builds them too.
SCRIPT_GUIDE = next(
    name
    for name in ("python-scripts.md", "ingestion-scripts.md")
    if (ROOT / "docs" / "guides" / name).is_file()
)


def contract_list() -> str:
    """Read explicit exports without importing optional warehouse drivers."""
    if not (ROOT / "docs/reference/compatibility.md").is_file():
        return ""
    lines = ["## Supported Python contracts\n\n"]
    for relative in (
        "__init__.py",
        "config/__init__.py",
        "services/operations/__init__.py",
        "dialects/engine/__init__.py",
        "dialects/warehouse/__init__.py",
    ):
        source = SRC / "etl_craft" / relative
        module = ".".join(("etl_craft", *Path(relative).parts[:-1]))
        exports = next(
            ast.literal_eval(node.value)
            for node in ast.parse(source.read_text(encoding="utf-8")).body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
        )
        target = relative.removesuffix("__init__.py") + "index.md"
        for name in exports:
            lines.append(f"- [`{module}.{name}`]({target})\n")
    for name in ("ScriptTask", "ScriptResult", "Offset", "ValidationTask"):
        lines.append(f"- [`etl_craft.scripting.{name}`](scripting.md#etl_craft.scripting.{name})\n")
    lines.append(
        "\nOnly these explicit exports and scripting types carry the Python compatibility "
        "promise in the [compatibility policy](../../reference/compatibility.md). "
        "Everything else in this browsable reference is implementation detail with no "
        "compatibility promise.\n\n"
    )
    return "".join(lines)


nav = mkdocs_gen_files.Nav()
for source in sorted((SRC / "etl_craft").rglob("*.py")):
    parts = source.relative_to(SRC).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
        page = Path(*parts, "index.md")
    else:
        page = Path(*parts).with_suffix(".md")
    if any(part.startswith("_") for part in parts):
        continue

    nav[parts] = page.as_posix()
    with mkdocs_gen_files.open(Path("api", page), "w", encoding="utf-8") as handle:
        if parts == ("etl_craft",):
            handle.write(
                "# Python API\n\n"
                "Use these references alongside the guides: signatures, types and docstrings "
                "come from the installed source. The Python-script contract is the entry "
                "point for writing Python tasks. Other modules describe the engine's current "
                "implementation; compatibility guarantees follow the installed "
                "release's policy.\n\n"
                "## Start here\n\n"
                "- [Python script types](scripting.md): `ScriptTask`, `ScriptResult` and "
                "`Offset`, with the data a task receives and returns.\n"
                f"- [Writing Python scripts](../../guides/{SCRIPT_GUIDE}): examples, "
                "offsets, warehouse access and logging.\n"
                "- [Configuration](config/index.md): loading the project configuration "
                "and resolving its settings.\n"
                "- [Core errors](core/errors.md): named errors and their exit statuses.\n\n"
                + (
                    "- [Service operations](services/operations/index.md): actor-scoped calls "
                    "and structured result documents.\n"
                    "- [Calling operations and JSON output](../../guides/service-operations.md): "
                    "Python and CLI examples.\n\n"
                    if (SRC / "etl_craft/services/operations/__init__.py").is_file()
                    else ""
                )
                + contract_list()
                + "## Packages\n\n"
            )
        if source.stem == "__init__":
            children = sorted(
                child
                for child in source.parent.iterdir()
                if not child.name.startswith("_")
                and (child.suffix == ".py" or (child / "__init__.py").is_file())
            )
            for child in children:
                target = f"{child.name}/index.md" if child.is_dir() else f"{child.stem}.md"
                handle.write(f"- [{child.stem}]({target})\n")
            handle.write("\n")
        handle.write(f"::: {'.'.join(parts)}\n")
    mkdocs_gen_files.set_edit_path(Path("api", page), Path("..") / source.relative_to(ROOT))

with mkdocs_gen_files.open("api/SUMMARY.md", "w", encoding="utf-8") as handle:
    handle.writelines(nav.build_literate_nav())
