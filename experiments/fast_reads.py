"""Local catalog experiment. Run with PYTHONPATH=src:tests and one size per process."""

import gzip
import json
import resource
import sys
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from sqlalchemy import bindparam, event

from fixtures.catalog_scale import seed_catalog
from fixtures.engine_db import sqlite_engine_db
from etl_craft.core.actor import SYSTEM_ACTOR, acting_as
from etl_craft.engine.queries import statement
from etl_craft.engine.schema import init_db
from etl_craft.services.catalog import document
from etl_craft.services.catalog.collect import build_catalog, collect_catalog


def measured(name, action):
    started = perf_counter()
    result = action()
    print(name, round(perf_counter() - started, 4), flush=True)
    return result


@contextmanager
def sql_counts(engine):
    statements = []
    def count(*_):
        statements.append(1)
    event.listen(engine, "before_cursor_execute", count)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", count)
        print("statements", len(statements), flush=True)


def encode(value):
    return json.dumps(value, ensure_ascii=True).encode()


def byte_counts(label, data):
    print(label, len(data), len(gzip.compress(data, compresslevel=1)), flush=True)


def index_triggers(catalog):
    by_target = defaultdict(dict)
    for label, task in catalog.tasks.items():
        target = task.params.get("TRIGGER_PIPELINE_CODE")
        if target is not None:
            by_target[target][label] = task
    original = document._pipeline
    def pipeline(catalog, asset):
        return original(replace(catalog, tasks=by_target[asset.row.pipeline_code]), asset)
    document._pipeline = pipeline
    try:
        return document.catalog_document(catalog)
    finally:
        document._pipeline = original


class Latest:
    """Benchmark the representation only. Caller supplies current access and version."""

    def publish(self, revision, rows, tasks):
        grouped = defaultdict(list)
        for task in tasks:
            grouped[task["pipeline"]].append({
                k: task[k] for k in ("code", "handler", "target", "sources", "documentation", "lineage")
            })
        shards = {}
        for row in rows:
            definition = {k: row[k] for k in ("code", "name", "description", "tasks", "upstream", "downstream")}
            shards[row["code"]] = (definition["name"], encode(definition | {"definitions": grouped[row["code"]]}))
        self.generation = revision, shards

    def read(self, revision, visible, code, validator=None):
        generation, shards = self.generation
        if code not in visible:
            return 403, b""
        if revision != generation:
            return 503, b""
        etag = f'"{revision}:{code}"'
        return (304, b"") if validator == etag else (200, shards[code][1])

    def index(self, visible):
        _, shards = self.generation
        return encode([{"code": code, "name": shards[code][0]} for code in sorted(visible)])


def main(count):
    with tempfile.TemporaryDirectory() as directory, acting_as(SYSTEM_ACTOR):
        if count:
            db = sqlite_engine_db(Path(directory))
            init_db(db.engine)
            with db.engine.begin() as conn:
                measured("seed", lambda: seed_catalog(conn, prefix="SCALE", pipelines=count, tasks=10, runs=25))
            engine, config = db.engine, db.config
        else:
            from etl_craft.config.loader import load_config
            from etl_craft.engine.connection import engine_db
            config = load_config(Path(sys.argv[2]) / "craft-connector.yml")
            engine = engine_db(config)
        for phase in ("cold", "warm"):
            with sql_counts(engine):
                if count == 5000:
                    # S7.BD bind limit prevents ordinary SQLite publication at this size.
                    catalog = measured(phase + " collect without global lineage recording",
                                       lambda: collect_catalog(engine, config, record_lineage=False))
                else:
                    catalog = measured(phase + " build", lambda: build_catalog(engine, config))
        baseline = measured("current document assembly", lambda: document.catalog_document(catalog))
        current = measured("current JSON encoding", lambda: encode(baseline))
        byte_counts("document bytes and gzip", current)
        bounded = measured("indexed document assembly", lambda: index_triggers(catalog))
        assert baseline == bounded
        latest = Latest()
        measured("shard publication", lambda: latest.publish("v1", bounded["pipelines"], bounded["tasks"]))
        _, shards = latest.generation
        visible = set(shards)
        code = sorted(visible)[0]
        index = measured("index full access", lambda: latest.index(visible))
        restricted = measured("index 1 percent", lambda: latest.index(set(sorted(visible)[:max(1, len(visible)//100)])))
        byte_counts("index bytes and gzip", index)
        byte_counts("restricted bytes and gzip", restricted)
        byte_counts("one pipeline bytes and gzip", latest.read("v1", visible, code)[1])
        print("total stored shard bytes", sum(len(body) for _, body in shards.values()), flush=True)
        print("process max RSS KiB", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, flush=True)
        assert latest.read("v1", visible, code, f'"v1:{code}"') == (304, b"")
        assert latest.read("v1", set(), code, f'"v1:{code}"') == (403, b"")
        assert latest.read("v2", visible, code, f'"v1:{code}"') == (503, b"")
        previous = latest.generation
        try:
            latest.publish("v2", bounded["pipelines"], [*bounded["tasks"], {}])
        except KeyError:
            assert latest.generation is previous
        else:
            raise AssertionError("a malformed build must fail")
        latest.publish("v2", bounded["pipelines"], bounded["tasks"])
        assert latest.read("v2", visible, code, f'"v1:{code}"')[0] == 200
        with engine.connect() as conn:
            query = statement(conn, "pipeline_run_history").bindparams(
                bindparam("pipeline_ids", expanding=True), bindparam("statuses", expanding=True))
            ids = list(conn.exec_driver_sql("SELECT PIPELINE_ID FROM CFG_PIPELINES").scalars())
            for phase, before, filtered in (("first", None, 0), ("deep", len(ids)*5, 0),
                                            ("filtered", None, 1)):
                params = dict(pipeline_ids=ids, statuses=["SUCCESS"], run_id=None, before=before,
                              status_filter=filtered, pool=None, agent=None, failure_class=None, limit=50)
                rows = measured("project history " + phase, lambda: conn.execute(query, params).all())
                print("returned", len(rows), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]))
