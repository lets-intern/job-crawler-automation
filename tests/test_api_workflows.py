"""워크플로우 승격 API 테스트.

실사이트에 나가지 않는다. 승격은 DB 상태만 보고 판정하므로 fetch 클라이언트가 필요 없다.
확인하는 것은 `workflows` 행과 `crawlers.status` 다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import workflows as workflows_api
from app.main import app

LIST_URL = "https://www.python.org/jobs/"


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
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

    app.dependency_overrides[workflows_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def add_crawler(conn: sqlite3.Connection, status: str) -> int:
    cursor = conn.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES (?, ?, ?)",
        ("python.org", LIST_URL, status),
    )
    return int(cursor.lastrowid or 0)


def crawler_status(conn: sqlite3.Connection, crawler_id: int) -> str:
    row = conn.execute("SELECT status FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    return str(row["status"])


def test_tested_크롤러는_승격되고_promoted_가_된다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = add_crawler(conn, "tested")

    response = client.post(
        "/api/workflows",
        json={
            "crawler_id": crawler_id,
            "name": "python.org 채용",
            "interval_minutes": 60,
            "auto_stop_threshold": 3,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["interval_minutes"] == 60
    assert body["auto_stop_threshold"] == 3
    assert body["crawler_status"] == "promoted"
    assert crawler_status(conn, crawler_id) == "promoted"

    row = conn.execute("SELECT * FROM workflows WHERE id = ?", (body["id"],)).fetchone()
    assert row["crawler_id"] == crawler_id
    assert row["name"] == "python.org 채용"
    assert row["interval_minutes"] == 60
    assert row["status"] == "active"
    assert (row["success_count"], row["fail_count"], row["last_run_at"]) == (0, 0, None)


def test_이름을_비우면_크롤러_이름을_쓴다(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = add_crawler(conn, "tested")

    body = client.post("/api/workflows", json={"crawler_id": crawler_id}).json()

    assert body["name"] == "python.org"
    # 기본 주기는 workflows 테이블 기본값과 같다
    assert body["interval_minutes"] == 360
    assert body["auto_stop_threshold"] is None


def test_draft_크롤러의_승격은_거부한다(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = add_crawler(conn, "draft")

    response = client.post("/api/workflows", json={"crawler_id": crawler_id})

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "not_tested"
    assert crawler_status(conn, crawler_id) == "draft"
    assert conn.execute("SELECT count(*) AS n FROM workflows").fetchone()["n"] == 0


def test_이미_승격된_크롤러는_다시_승격하지_않는다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = add_crawler(conn, "promoted")

    response = client.post("/api/workflows", json={"crawler_id": crawler_id})

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "not_tested"
    assert conn.execute("SELECT count(*) AS n FROM workflows").fetchone()["n"] == 0


def test_없는_크롤러는_404_다(client: TestClient) -> None:
    assert client.post("/api/workflows", json={"crawler_id": 999}).status_code == 404


def test_주기는_1분_미만을_받지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = add_crawler(conn, "tested")

    response = client.post("/api/workflows", json={"crawler_id": crawler_id, "interval_minutes": 0})

    assert response.status_code == 422
    assert crawler_status(conn, crawler_id) == "tested"
