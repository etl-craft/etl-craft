"""The rendered reference gate rejects an empty article even when navigation has the terms."""

import pytest

from fixtures.scripts import load

pytestmark = pytest.mark.unit
checker = load("check_docs_content")


def test_api_content_gate_rejects_empty_pages_and_nav_only_links(tmp_path):
    for relative in ("api/etl_craft/index.html", "api/etl_craft/scripting/index.html"):
        page = tmp_path / relative
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            "<nav>Python API ScriptTask ScriptResult Offset row_count</nav>"
            "<article>etl_craft</article>"
        )
    failures = checker.problems(tmp_path)
    assert any("missing Python API content" in failure for failure in failures)
    assert any("missing Python API link" in failure for failure in failures)


def test_api_content_gate_reports_missing_pages(tmp_path):
    assert len(checker.problems(tmp_path)) == 2


def test_api_content_gate_accepts_rendered_contracts_and_entry_points(tmp_path):
    policy = tmp_path / "reference/compatibility/index.html"
    policy.parent.mkdir(parents=True)
    policy.write_text("<article>Compatibility</article>")
    root = tmp_path / "api" / "etl_craft"
    (root / "scripting").mkdir(parents=True)
    (root / "index.html").write_text(
        "<article>Python API ScriptTask ScriptResult Offset "
        "etl_craft.__version__ etl_craft.config.load_config "
        "etl_craft.services.operations.OperationContext "
        "etl_craft.dialects.engine.EngineDialect "
        "etl_craft.dialects.warehouse.WarehouseDialect "
        "etl_craft.scripting.ValidationTask"
        '<a href="scripting/">script</a><a href="config/">config</a>'
        '<a href="core/errors/">errors</a></article>'
    )
    (root / "scripting/index.html").write_text(
        "<article>ScriptTask ScriptResult Offset row_count"
        '<h2 id="etl_craft.scripting.ScriptTask">task</h2>'
        '<h2 id="etl_craft.scripting.ScriptResult">result</h2>'
        '<h2 id="etl_craft.scripting.Offset">offset</h2></article>'
    )
    recipe = tmp_path / "guides/export-engine-data/index.html"
    recipe.parent.mkdir(parents=True)
    recipe.write_text("<article>Export Engine DB data</article>")
    assert checker.problems(tmp_path) == []
    recipe.unlink()
    assert any("export-engine-data" in failure for failure in checker.problems(tmp_path))
    recipe.write_text("<article>Export Engine DB data</article>")
    landing = root / "index.html"
    landing.write_text(
        "<article>Python API ScriptTask ScriptResult Offset"
        '<a href="scripting/">script</a><a href="config/">config</a>'
        '<a href="core/errors/">errors</a></article>'
    )
    assert any("etl_craft.config.load_config" in failure for failure in checker.problems(tmp_path))
