"""AUTO_RESTART_CONDITION is a config-file column: stored, exported and refused when bad."""

import csv

import pytest
from sqlalchemy import text

from etl_craft.core.errors import MetadataFileError
from etl_craft.services.config_files import export_config, read_config_files, sync_config
from fixtures.metadata import add_pipeline


def restart_of(engine, code):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT AUTO_RESTART_CONDITION AS value FROM CFG_PIPELINES WHERE PIPELINE_CODE=:c"
            ),
            {"c": code},
        ).scalar_one()


def set_in_file(folder, code, value):
    path = folder / "pipelines.csv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        if row["PIPELINE_CODE"] == code:
            row["AUTO_RESTART_CONDITION"] = value
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_a_pipeline_defaults_to_its_schedule_and_the_file_sets_and_exports_the_condition(
    engine_db, tmp_path
):
    with engine_db.engine.begin() as conn:
        add_pipeline(conn, "WATCH")
    assert restart_of(engine_db.engine, "WATCH") == "SCHEDULE"
    folder = tmp_path / "config"
    export_config(engine_db.engine, folder)
    set_in_file(folder, "WATCH", "SKIPPED|SCHEDULE|SUCCESS")
    sync_config(engine_db.engine, engine_db.config, read_config_files(folder), apply=True)
    assert (
        restart_of(engine_db.engine, "WATCH") == "SCHEDULE|SUCCESS|SKIPPED"
    )  # stored in canonical order
    again = tmp_path / "again"
    export_config(engine_db.engine, again)
    with (again / "pipelines.csv").open(newline="") as stream:
        assert (
            next(r for r in csv.DictReader(stream))["AUTO_RESTART_CONDITION"]
            == "SCHEDULE|SUCCESS|SKIPPED"
        )


def test_a_bad_condition_in_the_file_is_refused_naming_the_value(engine_db, tmp_path):
    with engine_db.engine.begin() as conn:
        add_pipeline(conn, "WATCH")
    folder = tmp_path / "config"
    export_config(engine_db.engine, folder)
    set_in_file(folder, "WATCH", "when-it-succeeds")
    with pytest.raises(MetadataFileError, match="when-it-succeeds"):
        read_config_files(folder)
    assert restart_of(engine_db.engine, "WATCH") == "SCHEDULE"
