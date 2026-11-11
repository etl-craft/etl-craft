"""Land validated reference corrections with each received file's identity."""

from etl_craft.scripting import ScriptResult, UploadReader


def run(task):
    """Replace this task's batch, retaining the admitted file identity."""

    def rows():
        for upload in task.uploads:
            source = UploadReader(upload, "CSV").rows(schema={"LOCKED": bool})
            header = next(source)
            for row in source:
                yield {name.lower(): value for name, value in zip(header, row, strict=True)} | {
                    "upload_id": upload.upload_id
                }

    return ScriptResult(row_count=task.replace_landing(rows()))
