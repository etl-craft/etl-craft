"""Check generation and access behavior with two isolated stores and a durable revision."""

from sqlite3 import OperationalError, connect

from fast_reads import Latest

ROWS = [{"code": "p", "name": "Pipeline", "description": None, "tasks": [],
         "upstream": [], "downstream": []}]


def current(conn):
    return conn.execute("SELECT version FROM revision").fetchone()[0]


def serve(conn, store, permitted, validator=None):
    try:
        revision = current(conn)
    except OperationalError:
        return 503, b""
    return store.read(revision, permitted, "p", validator)


def main():
    with connect(":memory:", isolation_level=None) as conn:
        conn.execute("CREATE TABLE revision (version TEXT)")
        conn.execute("INSERT INTO revision VALUES ('v1')")
        first, second = Latest(), Latest()
        for store in first, second:
            store.publish("v1", ROWS, [])
        assert serve(conn, first, {"p"}, '"v1:p"') == (304, b"")
        assert serve(conn, first, set(), '"v1:p"') == (403, b"")
        building_version = current(conn)
        conn.execute("UPDATE revision SET version = 'v2'")
        assert building_version != current(conn)
        assert serve(conn, first, {"p"}, '"v1:p"') == (503, b"")
        try:
            first.publish("v2", ROWS, [{}])
        except KeyError:
            assert first.generation[0] == "v1"
        else:
            raise AssertionError("a partial generation must fail")
        first.publish("v2", ROWS, [])
        assert serve(conn, first, {"p"}, '"v1:p"')[0] == 200
        assert serve(conn, second, {"p"}, '"v1:p"') == (503, b"")
        conn.execute("DROP TABLE revision")
        assert serve(conn, first, {"p"}, '"v2:p"') == (503, b"")
    print("Generation, revocation, interrupted build and failed version check assertions passed.")


if __name__ == "__main__":
    main()
