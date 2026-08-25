"""상세 URL 없이 등록하기.

상세를 JS 로 그려서 공고마다 주소가 따로 없는 사이트가 있다. 그런 사이트에 없는 주소를
지어내 가져오지 않는다 — 목록 페이지만 보고 만들고, 상세 셀렉터는 어느 HTML 에도 돌려보지
않은 채로 남는다.

그 상태는 실패가 아니라 건너뜀이다. 0개 매칭을 실패로 적으면 운영자는 고칠 곳으로 읽는데,
여기서는 볼 페이지가 없었을 뿐이다.

Gemini 도 실사이트도 부르지 않는다. 생성 의존성과 fetch 클라이언트를 갈아끼운다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.crawler.fetcher import FetchResult
from app.main import app
from app.selector.detail_path import document_path
from app.selector.discovery import Discovery
from app.selector.generator import GenerationResult, Usage
from app.selector.schema import SelectorSet, validate_selectors

LIST_URL = "https://www.samsungcareers.com/hr/"
DETAIL_URL = "https://www.samsungcareers.com/hr/1"

SELECTORS: dict[str, Any] = {
    "list": {
        "item": "ul.list > li",
        "title": "a.tit",
        "link": "a.tit",
        "date": "span.date",
    },
    "detail": {
        "title": "h1",
        "body": "div.cont",
        "requirements": "",
        "deadline": "",
        "department": "",
    },
}

# 상세 필드는 판정되지 않는다. 목록 필드만 실제 HTML 에 돌아간 결과다
MATCHES = {
    "list.item": 12,
    "list.title": 12,
    "list.link": 12,
    "list.date": 12,
    "list.company": 0,
    "detail.title": 0,
    "detail.body": 0,
    "detail.requirements": 0,
    "detail.deadline": 0,
    "detail.department": 0,
    "detail.company": 0,
}


class Verified:
    """검증 결과 대역. 상세 HTML 이 비어 있어 상세 필드가 0개로 온 모양이다."""

    list_missing = False
    failed_list_fields: list[str] = []
    failed = ["detail.title", "detail.body"]
    # 셀렉터가 비어 판정을 건너뛴 필드는 없다. 상세가 0개인 것은 볼 HTML 이 없어서다
    skipped: list[str] = []
    # 목록 항목 안의 필드는 잡혔다. 12.5 의 거절 대상이 아니다
    list_fields_missing = False

    def summary(self) -> dict[str, int]:
        return dict(MATCHES)


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


@pytest.fixture
def called_with() -> list[tuple[str, str]]:
    """생성이 어떤 (리스트 URL, 상세 URL) 로 불렸는지 쌓인다."""
    calls: list[tuple[str, str]] = []

    async def generate(list_url: str, detail_url: str, render_mode: str) -> GenerationResult:
        calls.append((list_url, detail_url))
        return GenerationResult(
            selectors=validate_selectors(SELECTORS),
            usage=Usage(
                model="gemini-3.5-flash",
                input_tokens=8000,
                output_tokens=120,
                total_tokens=8120,
                latency_ms=5000,
            ),
            attempts=1,
            verification=Verified(),  # type: ignore[arg-type]
        )

    app.dependency_overrides[crawlers_api.get_generator] = lambda: generate
    stub_discoverer()
    return calls


def saved(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM crawlers").fetchone()
    assert row is not None
    return row


def test_상세_URL_없이_등록된다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[tuple[str, str]]
) -> None:
    """빈 값이 거절 사유가 되지 않는다. 컬럼도 NULL 을 받는다."""
    response = client.post("/api/crawlers", json={"list_url": LIST_URL})

    assert response.status_code == 201
    assert response.json()["detail_url"] is None
    assert saved(conn)["detail_url"] is None
    assert called_with == [(LIST_URL, "")]


def test_공백만_적은_상세_URL_은_안_적은_것이다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[tuple[str, str]]
) -> None:
    response = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": "   "})

    assert response.status_code == 201
    assert saved(conn)["detail_url"] is None


def test_상세_필드는_실패가_아니라_건너뜀이다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[tuple[str, str]]
) -> None:
    """볼 페이지가 없어 판정하지 않은 것이다. 고칠 곳 목록에 섞지 않는다."""
    body = client.post("/api/crawlers", json={"list_url": LIST_URL}).json()

    assert body["failed_fields"] == []
    assert "detail.title" in body["skipped_fields"]
    assert "detail.body" in body["skipped_fields"]
    assert [name for name in body["skipped_fields"] if name.startswith("list.")] == []
    assert any("상세 URL 이 없어" in note for note in body["notes"])


def test_상세_URL_을_주면_건너뛰지_않는다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[tuple[str, str]]
) -> None:
    """볼 페이지가 있었으면 0개 매칭은 그대로 실패다."""
    body = client.post(
        "/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL}
    ).json()

    assert body["skipped_fields"] == []
    assert body["failed_fields"] == ["detail.title", "detail.body"]
    assert saved(conn)["detail_url"] == DETAIL_URL


def test_화면_결과에_건너뜀_이_단어로_나온다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[tuple[str, str]]
) -> None:
    """실패로 적으면 운영자는 고칠 곳으로 읽는다 (`.claude/rules/writing.md`)."""
    html = client.post("/ui/crawlers", data={"list_url": LIST_URL}).text

    assert "건너뜀" in html
    # 12.4 에서 문구가 "확인하지 않은 필드" 에서 바뀌었다. 셀렉터가 비어 건너뛴 것까지
    # 같은 줄에 들어오면서 상세 URL 만 가리키던 이름이 맞지 않게 됐다
    assert "건너뛴 필드" in html
    assert "손으로 고쳐야 하는 필드" not in html


async def test_상세_URL_이_없으면_목록만_가져온다(monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 주소를 지어내 가져오지 않는다. 기본 생성 경로가 그렇게 되어 있는지 본다."""
    fetched: list[str] = []
    generated: list[tuple[str, str]] = []

    class StubSource:
        async def fetch(self, url: str) -> FetchResult:
            fetched.append(url)
            return FetchResult(url=url, status_code=200, text="<ul class='list'></ul>")

    async def stub_generate_from_html(
        list_html: str, detail_html: str, **kwargs: Any
    ) -> GenerationResult:
        generated.append((list_html, detail_html))
        return GenerationResult(
            selectors=validate_selectors(SELECTORS),
            usage=Usage(
                model="gemini-3.5-flash",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                latency_ms=1,
            ),
            attempts=1,
            verification=Verified(),  # type: ignore[arg-type]
        )

    async def unreachable(*args: Any, **kwargs: Any) -> GenerationResult:
        raise AssertionError("상세 URL 이 없으면 두 페이지 경로로 가지 않는다")

    monkeypatch.setattr(crawlers_api, "get_fetcher", StubSource)
    monkeypatch.setattr(crawlers_api, "generate_from_html", stub_generate_from_html)
    monkeypatch.setattr(crawlers_api, "generate_for_urls", unreachable)

    generate = crawlers_api.get_generator()
    result = await generate(LIST_URL, "", "static")

    assert result.selectors.list.item == "ul.list > li"
    assert fetched == [LIST_URL]
    # 상세 HTML 은 빈 문자열로 들어간다. 없는 페이지를 대신할 것을 지어내지 않는다
    assert generated == [("<ul class='list'></ul>", "")]


def stub_discoverer() -> None:
    """경로 판정도 갈아끼운다. 기본 경로는 실사이트를 다시 가져오고 브라우저까지 연다.

    등록은 셀렉터 생성 다음에 상세로 가는 길을 알아본다 (`app/api/crawlers.py` 의
    `create_crawler`). 여기서 갈아끼우지 않으면 이 테스트가 네트워크에 매달린다
    (`.claude/rules/core.md`).
    """

    async def discover(list_url: str, selectors: SelectorSet) -> Discovery:
        return Discovery(
            list_mode="static",
            detail_mode="static",
            detail=document_path(f"{list_url}1/", "목록 항목의 링크를 그대로 따라간다"),
            evidence="정적 목록에서 항목과 상세 주소를 찾았다. 브라우저를 띄우지 않았다",
            list_count=1,
        )

    app.dependency_overrides[crawlers_api.get_discoverer] = lambda: discover
