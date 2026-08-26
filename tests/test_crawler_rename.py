"""크롤러 이름 고치기 (2.1).

등록이 이름을 안 받으면 리스트 URL 의 호스트가 그대로 이름이 된다 — `career.doosan.com`.
그 행을 다시 등록하면 경로 판정이 다시 돌아 브라우저와 모델을 쓰므로, 이름만 고치는 길이
있어야 한다.

여기서 보는 것은 넷이다 — API 가 저장하는가, 빈 이름을 거절하는가, 화면에 고칠 자리가
있는가, 이미 만들어진 워크플로우 이름이 따라오지 않는가.
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

LIST_URL = "https://career.doosan.com/dsp/sa/RecList.jsp"


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


def make_crawler(conn: sqlite3.Connection, name: str = "career.doosan.com") -> int:
    cursor = conn.execute(
        "INSERT INTO crawlers (name, list_url, status, list_mode) "
        "VALUES (?, ?, 'tested', 'static')",
        (name, LIST_URL),
    )
    return int(cursor.lastrowid or 0)


def stored_name(conn: sqlite3.Connection, crawler_id: int) -> str:
    row = conn.execute("SELECT name FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    return str(row["name"])


def test_the_name_can_be_changed_to_one_a_person_reads(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = make_crawler(conn)

    response = client.put(f"/api/crawlers/{crawler_id}/name", json={"name": "두산"})

    assert response.status_code == 200
    assert response.json() == {"id": crawler_id, "name": "두산"}
    assert stored_name(conn, crawler_id) == "두산"


def test_surrounding_spaces_are_dropped(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = make_crawler(conn)

    client.put(f"/api/crawlers/{crawler_id}/name", json={"name": "  두산  "})

    assert stored_name(conn, crawler_id) == "두산"


def test_an_empty_name_is_refused(client: TestClient, conn: sqlite3.Connection) -> None:
    """이름은 목록에서 그 행을 알아보는 유일한 값이다. 지울 수 있는 회사명과 다르다."""
    crawler_id = make_crawler(conn)

    response = client.put(f"/api/crawlers/{crawler_id}/name", json={"name": "   "})

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "empty_name"
    assert stored_name(conn, crawler_id) == "career.doosan.com"


def test_renaming_a_missing_crawler_is_404(client: TestClient) -> None:
    response = client.put("/api/crawlers/999/name", json={"name": "두산"})

    assert response.status_code == 404


def test_an_existing_workflow_keeps_its_own_name(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """워크플로우는 만들 때 이름을 복사해 자기 행에 들고 있다. 여기서 덮지 않는다."""
    crawler_id = make_crawler(conn)
    conn.execute(
        "INSERT INTO workflows (crawler_id, name) VALUES (?, ?)",
        (crawler_id, "career.doosan.com"),
    )

    client.put(f"/api/crawlers/{crawler_id}/name", json={"name": "두산"})

    row = conn.execute("SELECT name FROM workflows WHERE crawler_id = ?", (crawler_id,)).fetchone()
    assert str(row["name"]) == "career.doosan.com"


def test_the_list_screen_has_a_place_to_fix_the_name(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = make_crawler(conn)

    body = client.get("/ui/crawlers").text

    assert f'hx-put="/ui/crawlers/{crawler_id}/name"' in body
    assert 'value="career.doosan.com"' in body
    assert ">이름 저장</button>" in body


def test_saving_from_the_screen_stores_the_name(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = make_crawler(conn)

    body = client.put(f"/ui/crawlers/{crawler_id}/name", data={"name": "두산"}).text

    assert stored_name(conn, crawler_id) == "두산"
    assert "두산" in body


def test_the_screen_says_why_an_empty_name_was_refused(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """조각 라우트는 4xx 를 쓰지 않는다. 사유를 200 으로 화면에 적는다."""
    crawler_id = make_crawler(conn)

    response = client.put(f"/ui/crawlers/{crawler_id}/name", data={"name": "  "})

    assert response.status_code == 200
    assert "이름은 비울 수 없다" in response.text
    assert stored_name(conn, crawler_id) == "career.doosan.com"
