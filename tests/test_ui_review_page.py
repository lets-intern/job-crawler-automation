"""데이터 확인 화면(구 데이터 검수). 조회 조건이 접혀 있고 공고 목록이 먼저 보인다.

2026-08-29 결정. 조회 조건이 일곱 줄이라 열려 있으면 화면을 열 때마다 공고를 보려고 그만큼
내려야 한다. 접어 두되, `hx-trigger="load"` 는 접힌 채로도 그대로 돈다 — `details` 가 닫혀
있는 것은 DOM 에서 빠지는 것과 다르다.

실사이트에 나가지 않는다.
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


def test_화면_제목과_소제목이_확인으로_바뀌었다(client: TestClient) -> None:
    """PRD 없음. 2026-08-29 사용자 피드백 — '검수' 가 아니라 '확인' 용도로 쓰고 있다."""
    body = client.get("/review").text

    assert "<title>데이터 확인" in body
    assert "<h2" in body and "데이터 확인" in body
    assert "<h3>공고 목록</h3>" in body


def test_조회_조건이_details_로_접혀_있다(client: TestClient) -> None:
    body = client.get("/review").text

    assert "<details>" in body
    assert 'id="review-filters"' in body
    # details 여닫는 부분(summary) 안에 review-filters 가 있어야 접힌다
    details_start = body.index("<details>")
    filters_start = body.index('id="review-filters"')
    summary_end = body.index("</summary>", details_start)
    assert details_start < summary_end < filters_start


def test_접혀_있어도_조회_조건은_그대로_불러온다(client: TestClient) -> None:
    """`hx-trigger=\"load\"` 가 접힌 상태에서도 그대로 동다 — DOM 에서 빠진 것이 아니다."""
    body = client.get("/review").text

    filters_tag = body[body.index('id="review-filters"') :].split(">", 1)[0]
    assert 'hx-get="/ui/review/filters"' in filters_tag
    assert 'hx-trigger="load"' in filters_tag


def test_공고_목록은_접히지_않는다(client: TestClient) -> None:
    """공고가 먼저 보이는 것이 목적이다. 목록까지 접으면 아무 의미가 없다."""
    body = client.get("/review").text

    table_start = body.index('id="review-table"')
    # review-table 이전 마지막 details 가 review-filters 것이지 review-table 을 감싸지 않는다
    last_details_close_before_table = body.rindex("</details>", 0, table_start)
    last_details_open_before_table = body.rindex("<details>", 0, table_start)
    assert last_details_open_before_table < last_details_close_before_table < table_start
