"""회사 화면 (6.1.V).

보는 것은 셋이다. 네비게이션에 자리가 생겼는지, 그 주소가 열리면서 목록 조각을 부르는지,
그리고 행이 없을 때 화면이 "없음" 으로 끝내지 않고 언제 생기는지 말하는지.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import companies, db
from app.api.settings import get_connection
from app.api.ui import NAV
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

    app.dependency_overrides[get_connection] = request_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_네비게이션에_회사가_있다() -> None:
    assert ("/companies", "회사") in NAV


def test_회사_화면이_열리고_네비게이션이_켜진다(client: TestClient) -> None:
    response = client.get("/companies")

    assert response.status_code == 200
    assert '<a href="/companies" aria-current="page"' in response.text


def test_회사_화면이_목록_조각을_부른다(client: TestClient) -> None:
    assert 'hx-get="/ui/companies"' in client.get("/companies").text


def test_목록이_저장된_회사를_그린다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "삼성SDS", "삼성전자")
    companies.set_logo_url(conn, "삼성SDS", "https://cdn.test/sds.png")
    conn.commit()

    body = client.get("/ui/companies").text

    assert "삼성SDS" in body
    assert "삼성전자" in body
    assert "https://cdn.test/sds.png" in body


def test_로고가_없으면_빈_칸으로_두지_않는다(client: TestClient, conn: sqlite3.Connection) -> None:
    companies.ensure(conn, "토스")
    conn.commit()

    assert "로고 없음" in client.get("/ui/companies").text


def test_행이_없으면_언제_생기는지_말한다(client: TestClient) -> None:
    body = client.get("/ui/companies").text

    assert "정규화되면 그 회사명으로 행이 생긴다" in body
