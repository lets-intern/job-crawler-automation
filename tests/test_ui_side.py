"""부가 워크플로우 화면 (5.1.V ~ 5.6.V).

화면이 답해야 하는 것은 넷이다. 네비게이션에 자리가 있는가, 목록이 없을 때 무엇을 하면 되는지
말하는가, 등록·수정이 저장한 값이 스케줄러까지 가는가, 그리고 도는 동안 진행이 보이는가.

모델을 부르지 않는다. 실행이 걸리는 자리(`app/api/side.py` 의 `get_start`)를 갈아끼워, 대상이
없는 실행과 가짜 제공자로 도는 실행만 본다 (`.claude/rules/llm.md`: 실제 호출은 여기서 하지
않는다).
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import rules as rules_api
from app.api.ui import NAV
from app.main import app


@pytest.fixture
def path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "jobs.db"


@pytest.fixture
def conn(path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(path)
    db.migrate_up(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def client(path: pathlib.Path, conn: sqlite3.Connection) -> Iterator[TestClient]:
    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(path)
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[rules_api.get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_네비게이션에_부가_워크플로우가_있다() -> None:
    assert ("/side", "부가 워크플로우") in NAV


def test_부가_워크플로우_화면이_열리고_네비게이션이_켜진다(client: TestClient) -> None:
    response = client.get("/side")

    assert response.status_code == 200
    assert '<a href="/side" aria-current="page"' in response.text


def test_전달이_아무것도_보내지_않는다는_사실을_낱말로_적는다(client: TestClient) -> None:
    """PRD 3절. 실행 단추가 있는데 아무 일도 안 일어나는 화면을 만들지 않는다."""
    assert "아직 아무것도 보내지 않는다" in client.get("/side").text
