"""Admin erasure routes share the service and omit every personal value."""

import pytest
from fastapi.testclient import TestClient

from etl_craft.api.app import create_app
from fixtures.auth import service_token
from fixtures.erasure import erasure_project as erasure_project
from fixtures.seeds import seed_project as seed_project


@pytest.fixture
def erasure_client(erasure_project):
    ctx = erasure_project
    token = service_token(ctx.engine)
    with TestClient(create_app(ctx), base_url="https://testserver") as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client


def test_admin_preview_apply_list_and_validation_never_echo_key(erasure_client):
    client = erasure_client
    url = "/api/v1/projects/default/erasure"
    body = {
        "table": "ds.people",
        "column": "person",
        "value": "private-person-key",
        "reason": "request",
    }
    preview = client.post(url, json=body | {"dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] is True
    applied = client.post(url, json=body)
    assert applied.status_code == 200, applied.text
    listed = client.get(url)
    assert listed.status_code == 200, listed.text
    assert listed.json()["entries"][0]["subject_key"] == "[REDACTED]"
    refused = client.post(url, json=body | {"column": "missing"})
    assert refused.status_code != 200
    for response in (preview, applied, listed, refused):
        assert body["value"] not in response.text


@pytest.mark.parametrize("role", ["viewer", "operator", "developer"])
def test_non_admin_cannot_erase(erasure_project, erasure_client, role):
    from sqlalchemy import text

    from etl_craft.core.actor import acting_as

    ctx = erasure_project
    with acting_as(ctx.actor), ctx.engine.begin() as conn:
        conn.execute(
            text("UPDATE CFG_ACCOUNTS SET ROLE=:role WHERE ACCOUNT_NAME='test-admin'"),
            {"role": role},
        )
    response = erasure_client.post(
        "/api/v1/projects/default/erasure",
        json={
            "table": "ds.people",
            "column": "person",
            "value": "private-person-key",
            "reason": "request",
        },
    )
    assert response.status_code == 403
    assert "private-person-key" not in response.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("table", "ds.people; DROP TABLE ds.people"),
        ("column", 'person" OR 1=1 --'),
    ],
)
def test_identifiers_cannot_inject_sql(erasure_project, erasure_client, field, value):
    from sqlalchemy import text

    body = {
        "table": "ds.people",
        "column": "person",
        "value": "private-person-key",
        "reason": "request",
        field: value,
    }
    response = erasure_client.post("/api/v1/projects/default/erasure", json=body)
    assert response.status_code != 200
    assert body["value"] not in response.text
    with erasure_project.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM AUD_ERASURE_SUBJECTS")).scalar_one() == 0


def test_attacker_shaped_key_is_bound_and_deletes_only_it(erasure_project, erasure_client):
    import duckdb
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    ctx = erasure_project
    key = "private-key' OR 1=1 --"
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        conn.execute("INSERT INTO ds.people VALUES (?,3)", [key])
    statements = []

    def recorded(conn, cursor, statement, parameters, context, executemany):
        if "DELETE FROM" in statement.upper():
            statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", recorded)
    try:
        response = erasure_client.post(
            "/api/v1/projects/default/erasure",
            json={
                "table": "ds.people",
                "column": "person",
                "value": key,
                "reason": "request",
            },
        )
    finally:
        event.remove(Engine, "before_cursor_execute", recorded)
    assert response.status_code == 200, response.text
    assert sum(t["rows"] for t in response.json()["tables"]) == 1
    assert statements and all(key not in sql for sql, _ in statements)
    assert any(key in str(parameters) for _, parameters in statements)
    assert key not in response.text
    with duckdb.connect(str(ctx.config.project_dir / "warehouse.db")) as conn:
        assert set(conn.execute("SELECT person FROM ds.people").fetchall()) == {
            ("private-person-key",),
            ("retained",),
        }
