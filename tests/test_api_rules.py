"""정규화 규칙 CRUD API 테스트.

핵심 단언은 마지막 두 개다. 규칙을 추가하면 그 뒤에 정규화되는 건에는 적용되고, 이미
`normalized_jobs` 에 들어간 행은 값도 `normalized_at` 도 달라지지 않는다.

크롤링은 저장된 python.org 픽스처로 돈다. 실사이트에 나가지 않는다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import rules as rules_api
from app.crawler.runner import run_workflow
from app.main import app
from tests.test_normalize_pipeline import LIST_URL, SELECTORS, stub_fetcher


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        """
        INSERT INTO crawlers (name, list_url, selectors_json, status)
        VALUES (?, ?, ?, 'promoted')
        """,
        ("python.org", LIST_URL, json.dumps(SELECTORS)),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'python.org')")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(tmp_path: pathlib.Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[rules_api.get_connection] = request_connection
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


TRIM: dict[str, Any] = {"field_name": "title", "rule_type": "trim", "rule_config": {}}


def test_create_and_list(client: TestClient) -> None:
    created = client.post("/api/rules", json=TRIM)
    assert created.status_code == 201
    body = created.json()
    assert body["field_name"] == "title"
    assert body["rule_config"] == {"collapse_whitespace": True, "strip_chars": None}
    assert body["priority"] == 0
    assert body["enabled"] is True

    listed = client.get("/api/rules").json()
    assert [rule["id"] for rule in listed] == [body["id"]]


def test_list_orders_by_field_then_priority(client: TestClient) -> None:
    client.post("/api/rules", json={**TRIM, "priority": 2})
    client.post(
        "/api/rules",
        json={
            "field_name": "title",
            "rule_type": "regex",
            "rule_config": {"pattern": "x"},
            "priority": 1,
        },
    )
    client.post("/api/rules", json={**TRIM, "field_name": "body"})

    listed = client.get("/api/rules").json()
    assert [(rule["field_name"], rule["priority"]) for rule in listed] == [
        ("body", 0),
        ("title", 1),
        ("title", 2),
    ]


def test_create_rejects_invalid_config(client: TestClient) -> None:
    response = client.post(
        "/api/rules",
        json={"field_name": "title", "rule_type": "regex", "rule_config": {"pattern": "(["}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_config"


def test_create_rejects_unknown_field(client: TestClient) -> None:
    """`delivered_at` 은 제공 API 만 쓴다. 규칙으로 손댈 수 없어야 한다."""
    response = client.post(
        "/api/rules", json={"field_name": "delivered_at", "rule_type": "trim", "rule_config": {}}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unknown_field"


def test_create_rejects_unknown_type(client: TestClient) -> None:
    response = client.post(
        "/api/rules", json={"field_name": "title", "rule_type": "uppercase", "rule_config": {}}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unknown_type"


def test_update_changes_only_what_was_sent(client: TestClient) -> None:
    rule_id = client.post("/api/rules", json={**TRIM, "priority": 5}).json()["id"]

    updated = client.put(f"/api/rules/{rule_id}", json={"enabled": False}).json()
    assert updated["enabled"] is False
    assert updated["priority"] == 5
    assert updated["rule_type"] == "trim"


def test_update_validates_the_merged_rule(client: TestClient) -> None:
    """타입만 바꾸고 설정을 두면 맞지 않는다. 합쳐 놓고 봐야 알 수 있다."""
    rule_id = client.post("/api/rules", json=TRIM).json()["id"]

    response = client.put(f"/api/rules/{rule_id}", json={"rule_type": "regex"})
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_config"
    # 거절된 요청은 저장된 규칙을 건드리지 않는다
    assert client.get("/api/rules").json()[0]["rule_type"] == "trim"


def test_update_unknown_rule_is_404(client: TestClient) -> None:
    assert client.put("/api/rules/999", json={"enabled": False}).status_code == 404


def test_delete_removes_the_rule(client: TestClient) -> None:
    rule_id = client.post("/api/rules", json=TRIM).json()["id"]
    assert client.delete(f"/api/rules/{rule_id}").status_code == 204
    assert client.get("/api/rules").json() == []
    assert client.delete(f"/api/rules/{rule_id}").status_code == 404


def test_reorder_moves_several_rules_at_once(client: TestClient) -> None:
    first = client.post("/api/rules", json={**TRIM, "priority": 0}).json()["id"]
    second = client.post(
        "/api/rules",
        json={
            "field_name": "title",
            "rule_type": "regex",
            "rule_config": {"pattern": "x"},
            "priority": 1,
        },
    ).json()["id"]

    response = client.put(
        "/api/rules/order",
        json={"order": [{"id": first, "priority": 1}, {"id": second, "priority": 0}]},
    )
    assert response.status_code == 200
    assert [rule["id"] for rule in response.json()] == [second, first]


def test_reorder_rejects_unknown_rule(client: TestClient) -> None:
    rule_id = client.post("/api/rules", json=TRIM).json()["id"]
    response = client.put(
        "/api/rules/order",
        json={"order": [{"id": rule_id, "priority": 3}, {"id": 999, "priority": 0}]},
    )
    assert response.status_code == 404
    # 하나가 없으면 나머지도 옮기지 않는다
    assert client.get("/api/rules").json()[0]["priority"] == 0


async def test_new_rule_applies_only_to_later_rows(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """규칙 추가 전에 정규화된 행은 그대로, 추가 후에 정규화된 행에만 적용된다."""
    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=1)
    before = dict(conn.execute("SELECT * FROM normalized_jobs WHERE raw_job_id = 1").fetchone())
    assert "\n" in before["title"], "규칙 없이 들어간 값은 원문 그대로여야 한다"

    created = client.post("/api/rules", json=TRIM)
    assert created.status_code == 201

    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)

    after = dict(conn.execute("SELECT * FROM normalized_jobs WHERE raw_job_id = 1").fetchone())
    assert after == before, "기존 행은 값도 normalized_at 도 달라지지 않는다"

    fresh = conn.execute("SELECT * FROM normalized_jobs WHERE raw_job_id = 2").fetchone()
    assert fresh is not None
    assert fresh["title"] == " ".join(before["title"].split())


async def test_rule_crud_does_not_renormalize(client: TestClient, conn: sqlite3.Connection) -> None:
    """규칙 저장이 재정규화를 부르지 않는다 (2026-08-21 결정)."""
    await run_workflow(conn, 1, fetcher=stub_fetcher(), limit=2)
    before = [dict(row) for row in conn.execute("SELECT * FROM normalized_jobs ORDER BY id")]
    assert len(before) == 2

    rule_id = client.post("/api/rules", json=TRIM).json()["id"]
    client.put(f"/api/rules/{rule_id}", json={"priority": 3})
    client.put("/api/rules/order", json={"order": [{"id": rule_id, "priority": 0}]})
    client.delete(f"/api/rules/{rule_id}")

    after = [dict(row) for row in conn.execute("SELECT * FROM normalized_jobs ORDER BY id")]
    assert after == before
