"""새 크롤러가 받는 기본 렌더 모드.

Gemini 도 실사이트도 브라우저도 부르지 않는다. 생성 의존성을 갈아끼우고, 확인하는 것은
`crawlers.render_mode` 에 무엇이 저장됐는가와 생성이 어느 모드로 불렸는가다.

검증 대상은 셋이다 (13.1.V).

| 확인 | 근거 |
|---|---|
| 값을 안 준 등록은 `playwright` | 대상 사이트 대부분이 JS 렌더다 |
| `static` 을 명시한 등록은 그대로 | 정적 경로는 지우지 않고 선택지로 남는다 |
| 이미 있는 행은 안 바뀐다 | 기본값 변경은 새 등록에만 걸린다. 마이그레이션이 아니다 |
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
from app.main import app
from app.selector.generator import GenerationResult, Usage
from app.selector.schema import validate_selectors

TEMPLATES = pathlib.Path(__file__).parent.parent / "app" / "templates"

LIST_URL = "https://www.python.org/jobs/"
DETAIL_URL = "https://www.python.org/jobs/8126/"

SELECTORS: dict[str, Any] = {
    "list": {
        "item": "ol.list-recent-jobs > li",
        "title": "span.listing-company-name > a",
        "link": "span.listing-company-name > a",
        "date": "span.listing-posted time",
    },
    "detail": {
        "title": "h1.listing-company span.company-name",
        "body": "div.job-description",
        "requirements": "",
        "deadline": "",
        "department": "span.listing-company-category a",
    },
}


class Verified:
    """검증 결과 대역. 전부 잡힌 생성이다.

    `app/selector/verify.py` 를 부르지 않는다. 여기서 보는 것은 어느 모드가 저장되는가이고,
    셀렉터가 몇 개 잡혔는지는 그 모듈의 테스트가 따로 본다.
    """

    list_missing = False
    failed: list[str] = []
    failed_list_fields: list[str] = []

    def summary(self) -> dict[str, int]:
        return {"list.item": 25}


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
def called_with() -> list[str]:
    """생성이 어떤 `render_mode` 로 불렸는지 쌓인다."""
    modes: list[str] = []

    async def generate(list_url: str, detail_url: str, render_mode: str) -> GenerationResult:
        modes.append(render_mode)
        return GenerationResult(
            selectors=validate_selectors(SELECTORS),
            usage=Usage(
                model="gemini-3.5-flash",
                input_tokens=10399,
                output_tokens=139,
                total_tokens=11229,
                latency_ms=5649,
            ),
            attempts=1,
            verification=Verified(),  # type: ignore[arg-type]
        )

    app.dependency_overrides[crawlers_api.get_generator] = lambda: generate
    return modes


def modes(conn: sqlite3.Connection) -> list[str]:
    return [str(row["render_mode"]) for row in conn.execute("SELECT render_mode FROM crawlers")]


def test_등록에_모드를_안_주면_렌더로_저장된다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[str]
) -> None:
    """대상 사이트 대부분이 JS 렌더다. 정적으로 시작하면 빈 목록부터 보게 된다."""
    response = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    assert response.status_code == 201
    assert response.json()["render_mode"] == "playwright"
    assert modes(conn) == ["playwright"]
    # 셀렉터 생성도 같은 모드로 간다. 정적으로 뽑은 셀렉터는 렌더된 DOM 과 다를 수 있다
    assert called_with == ["playwright"]


def test_빈_문자열도_기본값으로_읽는다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[str]
) -> None:
    """화면이 값을 못 실어 보낸 경우다. 안 고른 것이므로 기본값이 걸린다."""
    response = client.post(
        "/api/crawlers",
        json={"list_url": LIST_URL, "detail_url": DETAIL_URL, "render_mode": "  "},
    )

    assert response.status_code == 201
    assert modes(conn) == ["playwright"]


def test_정적을_명시한_등록은_정적으로_저장된다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[str]
) -> None:
    """정적 경로는 지우지 않았다. 고르면 그대로 저장된다."""
    response = client.post(
        "/api/crawlers",
        json={"list_url": LIST_URL, "detail_url": DETAIL_URL, "render_mode": "static"},
    )

    assert response.status_code == 201
    assert response.json()["render_mode"] == "static"
    assert modes(conn) == ["static"]
    assert called_with == ["static"]


def test_이미_있는_행은_새_기본값에_끌려가지_않는다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[str]
) -> None:
    """기본값 변경은 새 등록에만 걸린다. 잘 도는 정적 크롤러를 건드릴 이유가 없다."""
    conn.execute(
        "INSERT INTO crawlers (name, list_url, render_mode) VALUES ('기존', ?, 'static')",
        (LIST_URL,),
    )
    conn.commit()

    client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})
    db.migrate_up(conn)

    saved = conn.execute("SELECT render_mode FROM crawlers WHERE name = '기존'").fetchone()
    assert saved["render_mode"] == "static"


def test_화면_경로도_같은_기본값을_쓴다(
    client: TestClient, conn: sqlite3.Connection, called_with: list[str]
) -> None:
    """조각 라우트가 자기 기본값을 따로 들고 있으면 화면과 API 가 갈린다."""
    response = client.post("/ui/crawlers", data={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    assert response.status_code == 200
    assert modes(conn) == ["playwright"]


def test_등록_화면의_기본_선택도_렌더다() -> None:
    """폼이 정적을 보낸 채로 남아 있으면 저장값만 바뀐 것이 된다."""
    template = (TEMPLATES / "pages" / "crawlers.html").read_text(encoding="utf-8")

    assert '<input type="radio" name="render_mode" value="playwright" checked>' in template
    assert '<input type="radio" name="render_mode" value="static" checked>' not in template
