"""검수 편집 모달 (16.1).

실사이트에 나가지 않는다. 저장된 행을 넣고 화면 경로로만 고친다.

| 확인 | 깨지면 |
|---|---|
| 표의 값 칸이 모달을 여는 버튼 하나다 | 고치는 입구가 둘이 되어 어느 쪽이 저장된 값인지 모른다 |
| 모달이 규칙이 만든 값을 함께 보여준다 | 무엇을 바꾸는 것인지 모르고 고친다 |
| 저장 응답이 표의 그 칸을 OOB 로 함께 갈아 끼운다 | 모달을 닫았더니 표에 옛 값이 남는다 |
| 저장 응답이 모달을 닫으라고 알린다 | 저장했는데 모달이 그대로 열려 있다 |
| 전달된 행이면 모달 안에서 알린다 | 소비 측에 반영되지 않는 수정을 반영된 줄 알고 한다 |
| `delivered_at` 이 그대로다 | 이미 보낸 공고가 소비 측에 다시 간다 |
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.main import app

LIST_URL = "https://www.python.org/jobs/"
LONG_BODY = "본문 첫 줄\n" + ("이 자리는 표 칸 폭에 들어가지 않는 긴 본문이다. " * 20)


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "jobs.db")
    db.migrate_up(connection)
    connection.execute(
        "INSERT INTO crawlers (name, list_url, status) VALUES ('python.org', ?, 'promoted')",
        (LIST_URL,),
    )
    connection.execute("INSERT INTO workflows (crawler_id, name) VALUES (1, 'python.org 채용')")
    connection.execute(
        """
        INSERT INTO raw_jobs (id, workflow_id, source_url, raw_data_json, content_hash)
        VALUES (7, 1, ?, '{}', 'hash-7')
        """,
        (LIST_URL,),
    )
    connection.execute(
        """
        INSERT INTO normalized_jobs (raw_job_id, company, title, body, source_url)
        VALUES (7, '파이썬재단', '백엔드 개발자', ?, ?)
        """,
        (LONG_BODY, LIST_URL),
    )
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


def override_of(conn: sqlite3.Connection, field: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM job_field_overrides WHERE raw_job_id = 7 AND field_name = ?",
        (field,),
    ).fetchone()
    return None if row is None else str(row["value"])


def oob_ids(html: str) -> list[str]:
    """응답에 실려 표의 제자리로 들어가는 조각들. 표 전체가 오면 이 목록이 비어 있다."""
    return re.findall(r'<div id="([^"]+)" hx-swap-oob="true"', html)


def test_표의_값_칸이_모달을_여는_버튼이다(client: TestClient) -> None:
    """표 안에서 바로 고치는 입력은 남기지 않는다. 고치는 자리는 모달 하나다."""
    html = client.get("/ui/review").text

    assert 'id="review-open-7-body"' in html
    assert "data-modal-open" in html
    assert "/ui/review/modal/7/body" in html
    assert "<textarea" not in html  # 표 안에서 바로 고치는 입력이 없다
    assert 'hx-put="/ui/review/cells/7/body"' not in html


def test_모달이_규칙값과_지금_값을_함께_보여준다(client: TestClient) -> None:
    html = client.get("/ui/review/modal/7/body").text

    assert "본문 고치기" in html
    assert "규칙이 만든 값" in html
    assert "본문 첫 줄" in html
    assert "<textarea" in html  # 본문은 여러 줄 입력이다
    assert 'hx-put="/ui/review/cells/7/body"' in html


def test_모달_저장이_표의_그_칸을_함께_갈아_끼운다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    response = client.put("/ui/review/cells/7/body", data={"value": "사람이 고친 본문"})

    assert response.status_code == 200
    assert override_of(conn, "body") == "사람이 고친 본문"
    # 표의 그 칸, 보정 개수, 전달 칸 세 자리만 갈린다. 표 전체는 다시 그리지 않는다
    assert oob_ids(response.text) == [
        "review-cell-7-body",
        "review-override-count-7",
        "review-delivery-7",
    ]
    assert "사람이 고친 본문" in response.text
    assert "사람 보정" in response.text
    assert "<table" not in response.text
    # 표가 갈린 뒤에 닫는다. 먼저 닫으면 옛 값이 남은 표가 드러난다
    assert response.headers["HX-Trigger-After-Settle"] == "app-modal-done"


def test_모달에서_보정을_지우면_규칙값으로_돌아간다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    client.put("/ui/review/cells/7/title", data={"value": "사람이 고친 제목"})

    response = client.delete("/ui/review/cells/7/title")

    assert override_of(conn, "title") is None
    assert "제목 보정을 지웠다" in response.text
    assert "review-cell-7-title" in oob_ids(response.text)
    assert response.headers["HX-Trigger-After-Settle"] == "app-modal-done"


def test_전달된_행은_모달_안에서_알리고_전달_표시는_그대로다(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    conn.execute("UPDATE normalized_jobs SET delivered_at = '2020-01-01 00:00:00'")

    opened = client.get("/ui/review/modal/7/title").text
    assert "이미 전달된 행이다" in opened

    client.put("/ui/review/cells/7/title", data={"value": "전달 뒤에 고친 제목"})

    row = conn.execute("SELECT delivered_at FROM normalized_jobs WHERE raw_job_id = 7").fetchone()
    assert row["delivered_at"] == "2020-01-01 00:00:00"


def test_없는_필드는_표를_건드리지_않고_사유를_적는다(client: TestClient) -> None:
    html = client.get("/ui/review/modal/7/source_url").text

    assert "고칠 수 없는 필드다" in html
    assert oob_ids(html) == []


def test_없는_수집_건은_사유를_적는다(client: TestClient) -> None:
    html = client.get("/ui/review/modal/999/title").text

    assert "수집 건 999" in html
    assert oob_ids(html) == []
