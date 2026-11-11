"""FILE_VALIDATION may validate the files an event wait admitted in its own run."""

import json
import textwrap
from dataclasses import replace

import pytest
from sqlalchemy import text

from etl_craft.core.actor import Actor, ActorKind, acting_as
from etl_craft.core.errors import HandlerError, PermanentError, PermissionDeniedError
from etl_craft.engine import event_files, transitions
from etl_craft.execution.context import build_task_context
from etl_craft.handlers import file_validation, python_scripts
from etl_craft.services.stewardship_checks import validation_problems
from fixtures.metadata import (
    add_dependency,
    add_pipeline,
    add_task,
    finish_run,
    start_run,
    task_run,
)

TESTER = Actor("tester", ActorKind.USER)
CHECK = textwrap.dedent(
    """
    from etl_craft.scripting import PermanentError

    def validate(task):
        rows = task.reader.rows()
        if next(rows, None) != ("id", "name"):
            raise PermanentError("header must be id|name; send a corrected file")
    """
)
LOAD = (
    "from etl_craft.scripting import ScriptResult\n"
    "def run(task):\n    return ScriptResult(len(task.event_files))\n"
)


@pytest.fixture
def scene(engine_db, tmp_path, request):
    opted_in = getattr(request, "param", True)
    config = replace(engine_db.config, config_path=tmp_path / "craft-connector.yml")
    (tmp_path / "validation_scripts").mkdir()
    (tmp_path / "validation_scripts" / "check.py").write_text(CHECK)
    config.python_scripts_dir.mkdir()
    (config.python_scripts_dir / "load.py").write_text(LOAD)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    good, bad = inbox / "good.csv", inbox / "bad.csv"
    good.write_text("id|name\n1|a\n")
    bad.write_text("wrong|header\n1|a\n")
    engine = engine_db.engine
    with acting_as(TESTER), engine.begin() as conn:
        pipeline = add_pipeline(conn, "P")
        wait = add_task(conn, pipeline, "wait", "EVENT_WAIT", EVENT_FILE=str(inbox / "*.csv"))
        validate = add_task(
            conn,
            pipeline,
            "validate",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
            **({"SOURCE_EVENT": "wait"} if opted_in else {}),
        )
        load = add_task(conn, pipeline, "load", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        bypass = add_task(conn, pipeline, "bypass", "PYTHON", SCRIPT_FILE="python_scripts/load.py")
        add_dependency(conn, pipeline, validate, wait)
        add_dependency(conn, pipeline, load, validate, "HAS_DATA")
        add_dependency(conn, pipeline, bypass, wait)
        run = start_run(conn, pipeline)
        wait_run = task_run(conn, wait, run)
        paths = [str(good.resolve()), str(bad.resolve())]
        evidence = {"files": [{"path": p, "size": 1, "mtime_ns": 1} for p in paths]}
        conn.execute(
            text("INSERT INTO AUD_TASK_EVENTS (TASK_RUN_ID, EVIDENCE) VALUES (:r, :e)"),
            {"r": wait_run, "e": json.dumps(evidence)},
        )
        for path in paths:
            conn.execute(
                text(
                    "INSERT INTO AUD_EVENT_FILES (TASK_ID, FILE_PATH, TASK_RUN_ID) "
                    "VALUES (:t, :p, :r)"
                ),
                {"t": wait, "p": path, "r": wait_run},
            )
    return {
        "engine": engine,
        "config": config,
        "pipeline": pipeline,
        "run": run,
        "tasks": {"wait": wait, "validate": validate, "load": load, "bypass": bypass},
        "good": good,
        "bad": bad,
    }


def context(scene, task, **params):
    with acting_as(TESTER), scene["engine"].begin() as conn:
        binding = transitions.find_or_create_task_run(conn, scene["tasks"][task], scene["run"])
    built = build_task_context(scene["engine"], scene["config"], binding.task_run_id)
    return replace(built, task_params={**built.task_params, **params}) if params else built


def validate_files(scene, **params):
    with acting_as(TESTER):
        return file_validation.run(context(scene, "validate", **params), scene["engine"])


def accept_validation(scene):
    with acting_as(TESTER), scene["engine"].begin() as conn:
        binding = transitions.find_or_create_task_run(
            conn, scene["tasks"]["validate"], scene["run"]
        )
        transitions.finish_task_run(conn, binding.task_run_id, status="SUCCESS")


def decisions(scene):
    with scene["engine"].connect() as conn:
        rows = conn.execute(
            text(
                "SELECT FILE_PATH AS path, STATUS AS status, REASON AS reason, SHA256 AS sha256 "
                "FROM AUD_EVENT_FILE_DECISIONS ORDER BY DECISION_ID"
            )
        ).all()
    return [(r.path.rsplit("/", 1)[-1], r.status, r.reason, r.sha256) for r in rows]


def test_only_files_the_validation_accepted_reach_later_tasks(scene):
    for task in ("load", "bypass"):  # nothing is decided yet: no file is visible
        assert context(scene, task).event_files == ()
    result = validate_files(scene)
    assert (result.source_count, result.target_count, result.reject_count) == (2, 1, 1)
    by_name = {row[0]: row for row in decisions(scene)}
    good, bad = by_name["good.csv"], by_name["bad.csv"]
    assert good[:2] == ("good.csv", "ACCEPTED") and good[2] is None and len(good[3]) == 64
    assert bad[:2] == ("bad.csv", "REFUSED")
    assert all(part in bad[2] for part in ("bad.csv", "header must be id|name", "corrected file"))
    for task in ("load", "bypass"):  # a decision by a validation that did not succeed is not enough
        assert context(scene, task).event_files == ()
    accept_validation(scene)
    for task in ("load", "bypass"):  # a task need not depend on validation to be held back
        built = context(scene, task)
        assert built.event_files == (str(scene["good"].resolve()),)
        assert [p for p, *_ in built.event_digests] == [str(scene["good"].resolve())]


@pytest.mark.parametrize("scene", [False], indirect=True)
def test_without_the_opt_in_every_admitted_file_reaches_later_tasks(scene):
    both = {str(scene["good"].resolve()), str(scene["bad"].resolve())}
    for task in ("load", "bypass"):
        built = context(scene, task)
        assert set(built.event_files) == both and built.event_digests == ()
    assert decisions(scene) == []


def test_a_file_that_changes_after_acceptance_stops_the_task_that_would_read_it(scene):
    validate_files(scene)
    accept_validation(scene)
    scene["good"].write_text("id|name\n1|changed\n")
    with pytest.raises(HandlerError) as refused:
        python_scripts.run(context(scene, "load"), scene["engine"])
    message = str(refused.value)
    assert str(scene["good"].resolve()) in message
    assert "changed after FILE_VALIDATION accepted it" in message and "SHA-256=" in message


def test_a_retry_keeps_the_identity_the_first_validation_recorded(scene):
    validate_files(scene)
    scene["good"].write_text("id|name\n1|changed\n")
    with pytest.raises(HandlerError, match="accepted 0 of 2 files"):
        validate_files(scene)  # the retry refuses both: the other file never became valid
    good = [row for row in decisions(scene) if row[0] == "good.csv"]
    assert [row[1] for row in good] == ["ACCEPTED", "REFUSED"]
    assert "as first validated" in good[-1][2] and "deliver the corrected file" in good[-1][2]
    accept_validation(scene)
    assert context(scene, "load").event_files == ()  # the latest decision refused it


def test_no_files_pass_quietly_unless_files_are_required(scene):
    with acting_as(TESTER), scene["engine"].begin() as conn:
        finish_run(conn, scene["run"], "SUCCESS")
        scene["run"] = start_run(conn, scene["pipeline"])  # this run's wait admitted nothing
    empty = validate_files(scene)
    assert (empty.source_count, empty.target_count) == (0, 0)
    with pytest.raises(PermanentError) as required:
        validate_files(scene, REQUIRE_UPLOADS="Y")
    assert "no files admitted by wait in this run" in str(required.value)


def test_a_decision_is_refused_for_a_file_another_run_admitted(scene):
    with acting_as(TESTER), scene["engine"].begin() as conn:
        finish_run(conn, scene["run"], "SUCCESS")
        second = start_run(conn, scene["pipeline"])
        validation = task_run(conn, scene["tasks"]["validate"], second, "IN-PROGRESS")
        with pytest.raises(PermissionDeniedError) as refused:
            event_files.record(
                conn,
                event_files.ValidationScope(second, scene["pipeline"], "wait", validation),
                event_files.Decision(str(scene["good"].resolve()), ("0" * 64, 1)),
            )
    assert "not admitted by wait in this run" in str(refused.value)


def test_validate_requires_a_file_wait_the_validation_depends_on(scene):
    def problems(**params):
        built = context(scene, "validate", **params)
        with scene["engine"].connect() as conn:
            return validation_problems(conn, built)

    assert problems() == []
    assert "an active EVENT_WAIT task" in problems(SOURCE_EVENT="load")[0]
    assert "an active EVENT_WAIT task" in problems(SOURCE_EVENT="missing")[0]
    with acting_as(TESTER), scene["engine"].begin() as conn:
        conn.execute(
            text("UPDATE CFG_TASK_DEPENDENCY SET ACTIVE_FLAG='N' WHERE TASK_ID=:t"),
            {"t": scene["tasks"]["validate"]},
        )
    assert "without a SUCCESS dependency" in problems()[0]


def test_a_real_run_validates_event_files_and_loads_only_the_accepted_one(cli_project, tmp_path):
    p = cli_project
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "good.csv").write_text("id|name\n1|a\n")
    (inbox / "bad.csv").write_text("wrong|header\n")
    folder = p.config.project_dir / "validation_scripts"
    folder.mkdir()
    (folder / "check.py").write_text(CHECK)
    (p.config.python_scripts_dir / "load.py").write_text(
        "from etl_craft.scripting import ScriptResult\n"
        "def run(task):\n"
        "    print('LOADED ' + ','.join(f.rsplit('/', 1)[-1] for f in task.event_files))\n"
        "    return ScriptResult(len(task.event_files))\n"
    )
    with acting_as(TESTER), p.engine.begin() as conn:
        wait = add_task(
            conn,
            p.pipeline_id,
            "wait",
            "EVENT_WAIT",
            EVENT_FILE=str(inbox / "*.csv"),
            EVENT_SETTLE_SECONDS="0",
            EVENT_TIMEOUT_MINUTES="1",
            EVENT_POLL_SECONDS="1",
        )
        validate = add_task(
            conn,
            p.pipeline_id,
            "validate",
            "FILE_VALIDATION",
            SCRIPT_FILE="validation_scripts/check.py",
            FILE_FORMAT="CSV",
            SOURCE_EVENT="wait",
        )
        add_dependency(conn, p.pipeline_id, validate, wait)
        add_dependency(conn, p.pipeline_id, p.task_id, validate, "HAS_DATA")
    code, output = p.run("pipelines", "refresh")
    assert code == 0, output
    code, output = p.run(
        "run", "--reason", "test requested run", "--pipeline-code", "P", timeout=120
    )
    assert code == 0, output
    with p.engine.connect() as conn:
        log = conn.execute(
            text("SELECT STATUS AS status FROM AUD_PIPELINES_RUN_LOG ORDER BY PIPELINE_RUN_ID DESC")
        ).first()
        decided = {
            r.path.rsplit("/", 1)[-1]: r.status
            for r in conn.execute(
                text("SELECT FILE_PATH AS path, STATUS AS status FROM AUD_EVENT_FILE_DECISIONS")
            )
        }
    assert log.status == "SUCCESS"
    assert decided == {"good.csv": "ACCEPTED", "bad.csv": "REFUSED"}
    attempt_logs = list((p.config.log_dir).rglob("*.log"))
    assert any("LOADED good.csv" in f.read_text() for f in attempt_logs)
    assert not any("bad.csv" in f.read_text() for f in attempt_logs if "LOADED" in f.read_text())
