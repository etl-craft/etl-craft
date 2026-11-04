"""Recorded rule decisions gate managed SQL on every local warehouse."""

from fixtures.rule_flags import check_literal_keys, check_rule_flags


def test_sql_excludes_explicit_rule_flags(sql_world, caplog):
    caplog.set_level("INFO", logger="etl_craft.handlers.sql")
    check_rule_flags(sql_world)
    assert "types=REJECT expanded_key_count=1" in caplog.text
    assert "types=REJECT expanded_key_count=0" in caplog.text


def test_rule_keys_are_data_on_the_warehouse(sql_world):
    check_literal_keys(sql_world)
