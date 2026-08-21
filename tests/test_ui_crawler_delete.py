"""등록 화면의 삭제 수단 (12.3).

API 는 12.1 에서 끝났다. 여기서 보는 것은 화면 쪽 세 가지다 — 목록에 삭제 버튼이 있는가,
누르기 전에 한 번 확인을 받는가, 거절 사유가 화면에 그대로 나오는가.

삭제는 조각 라우트라 4xx 를 쓰지 않는다. HTMX 가 4xx 를 갈아 끼우지 않아 화면에 아무 일도
일어나지 않기 때문이고, 거절도 200 으로 나가되 사유를 적는다 (`app/api/ui_crawlers.py`).
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
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

    app.dependency_overrides[crawlers_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def make_crawler(conn: sqlite3.Connection, status: str = "draft") -> int:
    cursor = conn.execute(
        "INSERT INTO crawlers (name, list_url, status, render_mode) VALUES (?, ?, ?, 'static')",
        ("python.org 채용", LIST_URL, status),
    )
    return int(cursor.lastrowid or 0)


def crawler_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT count(*) AS n FROM crawlers").fetchone()["n"])


def test_the_list_has_a_delete_button(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = make_crawler(conn)

    body = client.get("/ui/crawlers").text

    assert f'hx-delete="/ui/crawlers/{crawler_id}"' in body
    assert ">삭제</button>" in body


def test_the_delete_button_asks_before_it_deletes(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """되돌릴 수 없는 동작이다. 확인 없이 한 번에 지워지면 안 된다."""
    make_crawler(conn)

    body = client.get("/ui/crawlers").text

    assert "hx-confirm=" in body
    assert "되돌릴 수 없다" in body


def test_deleting_removes_the_row_and_refreshes_the_list(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """지운 뒤 목록만 갈린다. 페이지를 다시 부르지 않는다 (OOB 로 목록 조각만 들어온다)."""
    crawler_id = make_crawler(conn)

    response = client.delete(f"/ui/crawlers/{crawler_id}")

    assert response.status_code == 200
    assert crawler_count(conn) == 0
    assert 'id="crawler-list" hx-swap-oob="true"' in response.text
    assert "지웠다" in response.text
    # 목록 조각만 갈린다. 레이아웃은 들어오지 않는다
    assert "<html" not in response.text


def test_deleting_a_promoted_crawler_shows_the_reason(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """API 가 409 로 거절한다. 화면은 그 사유를 그대로 적고 행은 남는다."""
    crawler_id = make_crawler(conn, status="promoted")

    response = client.delete(f"/ui/crawlers/{crawler_id}")

    assert response.status_code == 200
    assert "승격된 크롤러는 지울 수 없다" in response.text
    assert crawler_count(conn) == 1


def test_deleting_a_crawler_with_a_workflow_shows_the_workflow(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """워크플로우가 매달려 있으면 그 번호까지 알려야 운영자가 무엇을 먼저 지울지 안다."""
    crawler_id = make_crawler(conn)
    cursor = conn.execute(
        "INSERT INTO workflows (crawler_id, name) VALUES (?, '테스트 워크플로우')",
        (crawler_id,),
    )
    workflow_id = int(cursor.lastrowid or 0)

    response = client.delete(f"/ui/crawlers/{crawler_id}")

    assert f"워크플로우 {workflow_id}" in response.text
    assert crawler_count(conn) == 1


def test_deleting_a_missing_crawler_says_so(client: TestClient) -> None:
    response = client.delete("/ui/crawlers/999")

    assert response.status_code == 200
    assert "크롤러 999 가 없다" in response.text
