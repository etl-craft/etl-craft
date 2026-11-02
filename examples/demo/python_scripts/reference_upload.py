"""Land validated reference corrections with each received file's identity."""

from sqlalchemy import text

from etl_craft.scripting import ScriptResult, UploadReader


def run(task):
    """Land only the accepted files of this run, retaining their upload ids."""
    columns = task.input_params["columns"]
    target = task.table(task.input_params["target"])
    names = ", ".join(columns)
    bindings = ", ".join(":" + column for column in columns)
    written = 0
    with task.warehouse() as engine, engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {target} "
                f"({', '.join(column + ' VARCHAR(100)' for column in columns)},"
                "UPLOAD_ID BIGINT,LOCKED BOOLEAN)"
            )
        )
        conn.execute(text(f"DELETE FROM {target}"))
        for upload in task.uploads:
            rows = UploadReader(upload, "CSV").rows(schema={"LOCKED": bool})
            header = next(rows)
            for row in rows:
                values = dict(zip(header, row, strict=True))
                locked = values.pop("LOCKED", None)
                conn.execute(
                    text(
                        f"INSERT INTO {target} ({names},UPLOAD_ID,LOCKED) "
                        f"VALUES ({bindings},:upload,:locked)"
                    ),
                    values | {"upload": upload.upload_id, "locked": locked},
                )
                written += 1
    return ScriptResult(row_count=written)
