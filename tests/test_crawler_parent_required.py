"""크롤러 등록 화면이 모회사 이름을 필수로 받는다 (2026-08-29 결정).

전에는 "회사명이 페이지에 없는 사이트를 위한 선택 입력"이었다. 모회사는 운영자가 적은
값이어야지 시스템이 짐작한 값이면 안 된다는 결정으로, 등록 화면(`POST /ui/crawlers`)이
이 칸을 필수로 받게 됐다 — 비어 있으면 크롤러 이름을 대신 쓰던 옛 동작은 없다
(`app/normalize/engine.py` 의 `read_parent_company`).

`app/api/crawlers.py` 의 `create_crawler` 자체는 막지 않는다. 필수 검사는 사람이 마주치는
등록 화면(`app/api/ui_crawlers.py` 의 `create_crawler_fragment`) 한 곳에 있다 — 그 함수를
직접 쓰는 기존 테스트·가져오기 경로까지 막으면 파급이 너무 크다.
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
from app.selector.generator import GenerationResult

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


def use_generator() -> list[str]:
    """생성 의존성을 갈아끼운다. 호출됐는지 자체가 이 테스트의 핵심 확인 대상이다."""
    called: list[str] = []

    async def generate(list_url: str, detail_url: str, render_mode: str) -> GenerationResult:
        called.append(list_url)
        raise AssertionError("모회사 이름이 비었으면 생성을 아예 부르지 않아야 한다")

    app.dependency_overrides[crawlers_api.get_generator] = lambda: generate
    return called


def test_모회사_이름을_비우면_생성_전에_거절한다(client: TestClient) -> None:
    """어차피 거절할 요청에 브라우저·모델 비용을 쓰지 않는다."""
    called = use_generator()

    response = client.post("/ui/crawlers", data={"list_url": LIST_URL, "default_company": ""})

    assert response.status_code == 200
    assert "모회사 이름은 비울 수 없다" in response.text
    assert "시스템이 대신 짐작하지 않는다" in response.text
    assert called == []


def test_공백만_적어도_비운_것과_같다(client: TestClient) -> None:
    called = use_generator()

    response = client.post("/ui/crawlers", data={"list_url": LIST_URL, "default_company": "   "})

    assert response.status_code == 200
    assert "모회사 이름은 비울 수 없다" in response.text
    assert called == []


def test_default_company_를_아예_안_보내도_거절된다(client: TestClient) -> None:
    """폼 필드 기본값이 빈 문자열이다. 폼이 그 칸을 아예 빼고 보내도 같은 사유로 거절한다."""
    called = use_generator()

    response = client.post("/ui/crawlers", data={"list_url": LIST_URL})

    assert response.status_code == 200
    assert "모회사 이름은 비울 수 없다" in response.text
    assert called == []


def test_등록_화면의_입력칸에_필수_표시가_있다(client: TestClient) -> None:
    body = client.get("/").text

    assert "모회사 이름 (필수)" in body
    assert 'id="crawler-company"' in body
    assert 'name="default_company"' in body
    # required 속성이 실제로 그 입력에 붙어 있어야 브라우저도 빈 채 제출을 막는다
    field = body.split('id="crawler-company"', 1)[1].split("</p>", 1)[0]
    assert "required" in field
