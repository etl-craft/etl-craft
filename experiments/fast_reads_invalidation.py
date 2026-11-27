"""Measure version reads and commit-to-delivery on two local PostgreSQL connections."""

from contextlib import ExitStack
from statistics import median, quantiles
from time import perf_counter

from psycopg import connect

from fixtures.engine_db import postgres_admin


def report(name, values):
    print(name, "median/p95 ms", round(median(values)*1000, 3),
          round(quantiles(values, n=20)[18]*1000, 3))


def main():
    # Scratch table and listener channel are unique to this run.
    from uuid import uuid4
    name = "fast_reads_" + uuid4().hex
    with postgres_admin() as writer, ExitStack() as stack:
        readers = [stack.enter_context(connect(writer.info.dsn, password=writer.info.password,
                                              autocommit=True)) for _ in range(2)]
        writer.execute(f"CREATE TABLE {name} (revision bigint)")
        try:
            writer.execute(f"INSERT INTO {name} VALUES (0)")
            for reader in readers:
                reader.execute(f"LISTEN {name}")
            reads, notices = [], []
            for revision in range(1, 101):
                with writer.transaction():
                    writer.execute(f"UPDATE {name} SET revision = %s", (revision,))
                    writer.execute("SELECT pg_notify(%s, %s)", (name, str(revision)))
                    start = perf_counter()
                for reader in readers:
                    received = list(reader.notifies(timeout=1, stop_after=1))
                    notices.append(perf_counter() - start)
                    assert received[0].payload == str(revision)
                    start_read = perf_counter()
                    assert reader.execute(f"SELECT revision FROM {name}").fetchone() == (revision,)
                    reads.append(perf_counter() - start_read)
            report("one current revision read", reads)
            report("commit to listener consumption (two serial readers)", notices)
        finally:
            writer.execute(f"DROP TABLE {name}")


if __name__ == "__main__":
    main()
