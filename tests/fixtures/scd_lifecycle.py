"""SCD row lifecycle checks shared by local and cloud warehouses."""


def check_scd_lifecycle(w, target, kind):
    shape = "SELECT 1 AS id, CAST('Ann' AS VARCHAR(20)) AS name"
    w.setup(target, shape, kind)
    params = {
        "SQL_ACTION": kind,
        "TARGET_OBJECT": target,
        "MERGE_KEY": "id",
        "MERGE_COMPARE_COLUMNS": "name",
    }
    w.run(f"load_{target}", SELECT_QUERY=shape, **params)
    before = w.rows(f"SELECT * FROM {w.name(target)} ORDER BY row_id")
    unchanged = w.run(f"load_{target}", SELECT_QUERY=shape, **params)
    assert (unchanged.insert_count, unchanged.update_count) == (0, 0)
    assert w.rows(f"SELECT * FROM {w.name(target)} ORDER BY row_id") == before

    changed_shape = shape.replace("'Ann'", "'Anna'")
    w.run(f"load_{target}", SELECT_QUERY=changed_shape, **params)
    history = w.rows(f"SELECT * FROM {w.name(target)} WHERE active_flag = 'N' ORDER BY row_id")
    creation = w.rows(
        f"SELECT create_date, created_by FROM {w.name(target)} WHERE active_flag = 'Y'"
    )
    deletion = {
        "SQL_ACTION": "DELETE_ROWS",
        "TARGET_OBJECT": target,
        "MERGE_KEY": "id",
        "SELECT_QUERY": "SELECT 1 AS id",
    }
    assert w.run(f"delete_{target}", **deletion).delete_count == 1
    assert w.rows(
        f"SELECT active_flag, delete_flag FROM {w.name(target)} WHERE delete_flag = 'Y'"
    ) == [("N", "Y")]
    assert (
        w.rows(f"SELECT create_date, created_by FROM {w.name(target)} WHERE delete_flag = 'Y'")
        == creation
    )
    assert (
        w.rows(f"SELECT * FROM {w.name(target)} WHERE delete_flag = 'N' ORDER BY row_id") == history
    )
    deleted = w.rows(f"SELECT * FROM {w.name(target)} ORDER BY row_id")
    assert w.run(f"delete_{target}", **deletion).delete_count == 0
    assert w.rows(f"SELECT * FROM {w.name(target)} ORDER BY row_id") == deleted

    revived = w.run(f"load_{target}", SELECT_QUERY=changed_shape, **params)
    assert (revived.update_count, revived.insert_count) == (
        (1, 0) if kind == "SCD1_MERGE" else (0, 1)
    )
    assert w.rows(
        f"SELECT name, active_flag, delete_flag FROM {w.name(target)} WHERE active_flag = 'Y'"
    ) == [("Anna", "Y", "N")]
    if kind == "SCD2_MERGE":
        assert (
            w.rows(f"SELECT * FROM {w.name(target)} WHERE active_flag = 'N' ORDER BY row_id")
            == deleted
        )
    else:
        assert w.rows(f"SELECT create_date, created_by FROM {w.name(target)}") == creation
