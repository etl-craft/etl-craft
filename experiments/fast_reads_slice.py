"""Make a browse slice for the existing lineage page from an experimental catalog file."""

import json
import sys
from pathlib import Path


def main(source, output):
    with source.open() as file:
        document = json.load(file)
    pipeline = "SCALE_0"
    tasks = [task for task in document["tasks"] if task["pipeline"] == pipeline]
    labels = {task["label"] for task in tasks}
    tables = {table for task in tasks for table in [task["target"], *task["sources"]]}
    data = {
        **document,
        "pipelines": [row for row in document["pipelines"] if row["code"] == pipeline],
        "tasks": tasks,
        "tables": [row for row in document["tables"] if row["name"] in tables],
        "column_edges": [edge for edge in document["column_edges"] if edge["task"] in labels],
        "table_edges": [edge for edge in document["table_edges"] if edge["task"] in labels],
        "definition_edges": [],
        "gaps": [],
        "triggers": [],
    }
    output.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    print("persisted browse slice bytes", output.stat().st_size, flush=True)


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
