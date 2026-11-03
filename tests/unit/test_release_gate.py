import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.scripts import load

pytestmark = pytest.mark.unit

gate = load("release_gate")
suites_module = load("suites")

VERSION = "1.0.0"
SUITES_TOML = """
[suites.unit]
marker = "unit"

[suites.package]
marker = "package"
wheel = true
"""
WHEEL_SHA = hashlib.sha256(b"the wheel").hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "release").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{VERSION}"\n'
        '[tool.pytest.ini_options]\nmarkers = ["unit", "package", "e2e"]\n',
        encoding="utf-8",
    )
    (root / "release" / "required-suites.toml").write_text(SUITES_TOML, encoding="utf-8")
    (root / "module.py").write_text("x = 1\n", encoding="utf-8")
    (root / "test_suites.py").write_text(
        "import pytest\n"
        "@pytest.mark.unit\n@pytest.mark.parametrize('n', range(3))\n"
        "def test_unit(n): pass\n"
        "@pytest.mark.package\n@pytest.mark.parametrize('n', range(3))\n"
        "def test_package(n): pass\n"
        "@pytest.mark.e2e\n@pytest.mark.parametrize('n', range(3))\n"
        "def test_e2e(n): pass\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    setup_example(root)
    git(root, "init", "-q", "-b", "main")
    commit_all(root, "initial")
    return root


def suites(repo):
    return suites_module.load_suites(repo / "release" / "required-suites.toml")


def write_evidence(repo: Path, name: str, **overrides) -> None:
    evidence = {
        "schema": 2,
        "suite": name,
        "marker": name,
        "package_version": VERSION,
        "commit": git(repo, "rev-parse", "HEAD"),
        "dirty": False,
        "wheel_sha256": WHEEL_SHA if name == "package" else None,
        "exit_status": 0,
        "counts": {"passed": 3, "failed": 0, "error": 0, "skipped": 0, "xfailed": 0, "xpassed": 0},
        "platform_key": "linux",
        "collected": [f"test_suites.py::test_{name}[{i}]" for i in range(3)],
        "tests": [
            {"nodeid": f"test_suites.py::test_{name}[{i}]", "outcome": "passed"} for i in range(3)
        ],
    }
    if "counts" in overrides:
        outcomes = [outcome for outcome, count in overrides["counts"].items() for _ in range(count)]
        evidence["tests"] = [
            {"nodeid": f"test_suites.py::test_{name}[{i}]", "outcome": outcome}
            for i, outcome in enumerate(outcomes)
        ]
    evidence.update(overrides)
    path = repo / "release" / "evidence" / VERSION / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence), encoding="utf-8")


def problems(repo, wheel=None):
    return {
        result.suite: result.problems
        for result in gate.check(VERSION, repo, suites(repo), wheel or repo / "candidate.whl")
    }


def test_passing_evidence_for_every_suite_is_releasable(repo, capsys):
    write_evidence(repo, "unit")
    write_evidence(repo, "package")
    commit_all(repo, "record evidence")
    assert problems(repo) == {"unit": [], "package": [], "example-support-insights": []}
    assert gate.main(["--repo", str(repo), "--wheel", str(repo / "candidate.whl")]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "release gate for 1.0.0",
        "  OK    unit",
        "  OK    package",
        "  OK    example-support-insights",
        "releasable",
    ]


def test_a_suite_without_evidence_blocks_the_release(repo, capsys):
    write_evidence(repo, "unit")
    assert problems(repo)["package"] == ["no evidence (release/evidence/1.0.0/package.json)"]
    assert gate.main(["--repo", str(repo), "--wheel", str(repo / "candidate.whl")]) == 1
    assert capsys.readouterr().out.endswith("not releasable\n")


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"dirty": True}, "recorded from a working tree with uncommitted changes"),
        ({"dirty": None}, "recorded from a working tree with uncommitted changes"),
        ({"counts": {"passed": 2, "skipped": 1}}, "1 skipped"),
        ({"counts": {"passed": 2, "failed": 1}}, "1 failed"),
        ({"counts": {"passed": 2, "error": 1}}, "1 error"),
        ({"counts": {"passed": 2, "xfailed": 1}}, "1 xfailed"),
        ({"counts": {"passed": 0}}, "no tests ran"),
        ({"exit_status": 1}, "pytest exited with status 1"),
        ({"package_version": "0.9.0"}, "recorded at version '0.9.0', not 1.0.0"),
        ({"suite": "other"}, "evidence is for suite 'other'"),
        ({"schema": 1}, "unsupported evidence schema 1"),
        ({"commit": None}, "no commit recorded"),
    ],
)
def test_evidence_that_does_not_show_a_clean_pass_is_rejected(repo, overrides, problem):
    write_evidence(repo, "unit", **overrides)
    assert problem in problems(repo)["unit"]


def test_a_wheel_suite_must_record_its_wheel(repo):
    write_evidence(repo, "package", wheel_sha256=None)
    assert "no wheel recorded; run the suite with --wheel" in problems(repo)["package"]


def test_unreadable_evidence_is_rejected(repo):
    write_evidence(repo, "unit")
    path = repo / "release" / "evidence" / VERSION / "unit.json"
    path.write_text("{not json", encoding="utf-8")
    assert problems(repo)["unit"][0].startswith("unreadable evidence")
    path.write_text("[1, 2]", encoding="utf-8")
    assert problems(repo)["unit"] == ["unreadable evidence: not a JSON object"]


def test_evidence_from_a_commit_outside_the_history_is_rejected(repo):
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "module.py").write_text("x = 2\n", encoding="utf-8")
    side = commit_all(repo, "side change")
    git(repo, "checkout", "-q", "main")
    write_evidence(repo, "unit", commit=side)
    assert problems(repo)["unit"] == [f"commit {side[:12]} is not an ancestor of HEAD"]


def test_code_changed_after_the_evidence_invalidates_it(repo):
    write_evidence(repo, "unit")
    (repo / "module.py").write_text("x = 3\n", encoding="utf-8")
    commit_all(repo, "change code after testing")
    assert problems(repo)["unit"] == ["changed since the evidence was recorded: module.py"]


def test_changelog_and_release_notes_may_change_after_the_evidence(repo):
    write_evidence(repo, "unit")
    (repo / "CHANGELOG.md").write_text("## 1.0.0\n", encoding="utf-8")
    (repo / "docs" / "release-notes").mkdir(parents=True)
    (repo / "docs" / "release-notes" / "1.0.0.md").write_text("Notes\n", encoding="utf-8")
    commit_all(repo, "release notes")
    assert problems(repo)["unit"] == []


def test_wheel_suites_must_all_test_the_same_wheel(repo, tmp_path):
    two_wheels = SUITES_TOML + '\n[suites.e2e]\nmarker = "e2e"\nwheel = true\n'
    (repo / "release" / "required-suites.toml").write_text(two_wheels, encoding="utf-8")
    commit_all(repo, "declare e2e suite")
    write_evidence(repo, "package")
    write_evidence(repo, "e2e", wheel_sha256="0" * 64)
    found = {result.suite: result.problems for result in gate.check(VERSION, repo, suites(repo))}
    assert "wheel-bound suites tested different wheels" in found["package"]
    assert "wheel-bound suites tested different wheels" in found["e2e"]


def test_the_released_wheel_must_be_the_tested_one(repo, tmp_path):
    write_evidence(repo, "unit")
    write_evidence(repo, "package")
    tested = tmp_path / "tested.whl"
    tested.write_bytes(b"the wheel")
    other = tmp_path / "other.whl"
    other.write_bytes(b"a rebuilt wheel")
    assert problems(repo, wheel=tested)["package"] == []
    assert problems(repo, wheel=other)["package"] == [f"tested a different wheel than {other}"]


@pytest.mark.parametrize("marker", ["unit or package", "package", None])
def test_evidence_for_a_different_marker_is_rejected(repo, marker):
    write_evidence(repo, "unit", marker=marker)
    assert any("recorded marker" in problem for problem in problems(repo)["unit"])


@pytest.mark.parametrize(
    "nodes",
    [
        ["test_suites.py::test_unit[0]"],
        [f"test_suites.py::test_unit[{i}]" for i in range(3)] + ["test_suites.py::test_package[0]"],
    ],
)
def test_a_self_consistent_subset_or_extra_node_cannot_pass(repo, nodes):
    write_evidence(
        repo,
        "unit",
        collected=nodes,
        tests=[{"nodeid": node, "outcome": "passed"} for node in nodes],
        counts={"passed": len(nodes)},
    )
    assert any(
        "complete suite" in problem or "outside suite" in problem
        for problem in problems(repo)["unit"]
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"collected": []},
        {"collected": ["x", "x"]},
        {"collected": "x"},
        {"tests": []},
        {"tests": [{"nodeid": "x", "outcome": "unknown"}]},
        {"tests": ["bad"]},
        {"counts": {"passed": "3"}},
        {"platform_key": "unknown"},
    ],
)
def test_malformed_completeness_fields_fail_closed(repo, overrides):
    # Write the malformed JSON directly so the fixture does not synthesize outcomes from counts.
    write_evidence(repo, "unit")
    path = repo / "release" / "evidence" / VERSION / "unit.json"
    evidence = json.loads(path.read_text())
    evidence.update(overrides)
    path.write_text(json.dumps(evidence))
    assert problems(repo)["unit"]


def test_a_passing_setup_without_a_test_call_does_not_cover_the_suite(repo):
    write_evidence(
        repo,
        "unit",
        tests=[{"nodeid": "test_suites.py::test_unit[0]", "outcome": "passed"}],
        counts={"passed": 1},
    )
    assert "test outcomes do not cover exactly the collected test ids" in problems(repo)["unit"]


def test_collection_errors_refuse_the_release(repo):
    (repo / "test_broken.py").write_text("import missing_module_for_release_collection\n")
    commit_all(repo, "broken collection")
    write_evidence(repo, "unit")
    assert any("cannot collect suite" in problem for problem in problems(repo)["unit"])


def test_uncommitted_release_code_cannot_change_the_collected_suite(repo):
    write_evidence(repo, "unit")
    (repo / "module.py").write_text("x=4\n")
    assert any("release working tree" in problem for problem in problems(repo)["unit"])


def test_only_explicit_platform_nodes_may_differ(repo):
    manifest = (
        SUITES_TOML
        + """
[suites.unit.platform_only]
linux = ["test_platform.py::test_linux"]
darwin = ["test_platform.py::test_darwin"]
"""
    )
    (repo / "release" / "required-suites.toml").write_text(manifest)
    (repo / "test_platform.py").write_text(
        "import pytest\npytestmark=pytest.mark.unit\n"
        "def test_linux(): pass\ndef test_darwin(): pass\n"
    )
    commit_all(repo, "declare platform tests")
    other_platform = "darwin" if sys.platform == "linux" else "linux"
    other_node = f"test_platform.py::test_{other_platform}"
    nodes = [f"test_suites.py::test_unit[{i}]" for i in range(3)] + [other_node]
    write_evidence(
        repo,
        "unit",
        platform_key=other_platform,
        collected=nodes,
        tests=[{"nodeid": node, "outcome": "passed"} for node in nodes],
        counts={"passed": 4},
    )
    assert problems(repo)["unit"] == []
    nodes.remove(other_node)
    write_evidence(
        repo,
        "unit",
        platform_key=other_platform,
        collected=nodes,
        tests=[{"nodeid": node, "outcome": "passed"} for node in nodes],
        counts={"passed": 3},
    )
    assert any(other_node in problem for problem in problems(repo)["unit"])


def setup_example(root):
    fixture = Path(__file__).parents[1] / "fixtures/release_example/complete.json"
    manifest = json.loads(fixture.read_text())
    (root / "release/example.toml").write_text(
        f'commit = "{manifest["demo_commit"]}"\n'
        'checks = ["fixture-check"]\nscenarios = ["fixture-scenario"]\n'
    )
    path = root / "release/evidence" / VERSION / "example-support-insights.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    wheel = root / "candidate.whl"
    wheel.write_bytes(b"the wheel")
    os.utime(wheel, (1767225600, 1767225600))
    return path


def test_complete_example_manifest_is_accepted(repo):
    assert gate.check_example(VERSION, repo, repo / "candidate.whl").ok


@pytest.mark.parametrize("group", ["checks", "scenarios"])
@pytest.mark.parametrize(
    "fault", ["missing", "extra", "skipped", "failed", "duplicate", "counts", "evidence"]
)
def test_example_inventory_fails_closed(repo, group, fault):
    path = setup_example(repo)
    manifest = json.loads(path.read_text())
    entry = manifest[group][0]
    if fault == "missing":
        manifest[group] = []
    elif fault in ("extra", "duplicate"):
        manifest[group].append(dict(entry, id="extra" if fault == "extra" else entry["id"]))
    elif fault in ("skipped", "failed"):
        entry["outcome"] = fault
    else:
        entry[fault] = {} if fault == "counts" else []
    path.write_text(json.dumps(manifest))
    result = gate.check_example(VERSION, repo, repo / "candidate.whl")
    assert not result.ok
    assert all(
        str(path) in problem and group in problem and "expected" in problem
        for problem in result.problems
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wheel_sha256", "0" * 64),
        ("demo_commit", "f" * 40),
        ("started_at", "2025-01-01T00:00:00Z"),
        ("ended_at", "invalid"),
        ("started_at", "2026-01-02T00:00:00"),
    ],
)
def test_example_identity_and_freshness_fail_closed(repo, field, value):
    path = setup_example(repo)
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    result = gate.check_example(VERSION, repo, repo / "candidate.whl")
    assert not result.ok
    assert any(
        str(path) in problem and field in problem and "expected" in problem
        for problem in result.problems
    )


@pytest.mark.parametrize("group", ["checks", "scenarios"])
def test_empty_example_inventory_blocks_release(repo, group):
    pin = repo / "release/example.toml"
    pin.write_text(
        pin.read_text().replace(
            f'{group} = ["fixture-{"check" if group == "checks" else "scenario"}"]', f"{group} = []"
        )
    )
    result = gate.check_example(VERSION, repo, repo / "candidate.whl")
    assert any(str(pin) in problem and group in problem for problem in result.problems)


def test_example_requires_release_wheel(repo):
    result = gate.check_example(VERSION, repo, None)
    assert any("--wheel" in problem for problem in result.problems)


@pytest.mark.parametrize("document", ["pin", "manifest"])
@pytest.mark.parametrize("fault", ["missing", "malformed", "shape"])
def test_example_document_errors_name_the_file(repo, document, fault):
    path = (
        repo / "release/example.toml"
        if document == "pin"
        else repo / "release/evidence" / VERSION / "example-support-insights.json"
    )
    if fault == "missing":
        path.unlink()
    elif fault == "malformed":
        path.write_text("{invalid")
    else:
        path.write_text("commit = 12\nchecks = []\nscenarios = []\n" if document == "pin" else "[]")
    result = gate.check_example(VERSION, repo, repo / "candidate.whl")
    assert not result.ok
    assert any(str(path) in problem and "expected" in problem for problem in result.problems)


def test_bad_example_manifest_blocks_the_whole_gate(repo, capsys):
    write_evidence(repo, "unit")
    write_evidence(repo, "package")
    path = repo / "release/evidence" / VERSION / "example-support-insights.json"
    manifest = json.loads(path.read_text())
    manifest["scenarios"][0]["outcome"] = "skipped"
    path.write_text(json.dumps(manifest))
    commit_all(repo, "record incomplete demo")
    assert gate.main(["--repo", str(repo), "--wheel", str(repo / "candidate.whl")]) == 1
    assert "scenarios['fixture-scenario'].outcome" in capsys.readouterr().out
