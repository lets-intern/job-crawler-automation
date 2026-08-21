"""크롤러 등록·수동 보정 API 테스트.

Gemini 도 실사이트도 부르지 않는다. 생성 의존성을 갈아끼우고, 확인하는 것은 `crawlers` 행이
어떤 상태로 남는가다. 셀렉터 자체는 2.3.V 에서 실제 생성 호출로 얻은 것을 쓴다.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import crawlers as crawlers_api
from app.crawler.fetcher import RobotsDisallowedError, TransportError
from app.main import app
from app.selector.generator import GenerationResult, SelectorGenerationError, Usage
from app.selector.schema import validate_selectors
from app.selector.verify import verify_selectors

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LIST_HTML = (FIXTURES / "pythonorg-jobs-list-20260821.html").read_text(encoding="utf-8")
DETAIL_HTML = (FIXTURES / "pythonorg-job-detail-20260821.html").read_text(encoding="utf-8")

LIST_URL = "https://www.python.org/jobs/"
DETAIL_URL = "https://www.python.org/jobs/8126/"

GENERATED: dict[str, Any] = {
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

USAGE = Usage(
    model="gemini-3.5-flash",
    input_tokens=10399,
    output_tokens=139,
    total_tokens=11229,
    latency_ms=5649,
)


def result_for(payload: dict[str, Any]) -> GenerationResult:
    selectors = validate_selectors(payload)
    return GenerationResult(
        selectors=selectors,
        usage=USAGE,
        attempts=1,
        verification=verify_selectors(selectors, LIST_HTML, DETAIL_HTML),
    )


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
        """요청마다 같은 파일에 새 연결을 연다. 운영 경로와 같은 모양이다."""
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


def use_generator(result: Any) -> None:
    """생성 의존성을 갈아끼운다. `result` 가 예외면 그것을 던진다."""

    async def generate(list_url: str, detail_url: str) -> GenerationResult:
        if isinstance(result, Exception):
            raise result
        return result

    app.dependency_overrides[crawlers_api.get_generator] = lambda: generate


def rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM crawlers").fetchall()


def test_registration_stores_a_draft_row(client: TestClient, conn: sqlite3.Connection) -> None:
    use_generator(result_for(GENERATED))

    response = client.post(
        "/api/crawlers",
        json={"list_url": LIST_URL, "detail_url": DETAIL_URL, "name": "python.org 채용"},
    )

    assert response.status_code == 201
    saved = rows(conn)
    assert len(saved) == 1
    assert saved[0]["status"] == "draft"
    assert saved[0]["name"] == "python.org 채용"
    assert saved[0]["list_url"] == LIST_URL
    assert json.loads(saved[0]["selectors_json"]) == GENERATED
    assert response.json()["id"] == saved[0]["id"]


def test_registration_reports_matches_and_no_failed_field(client: TestClient) -> None:
    use_generator(result_for(GENERATED))

    body = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    payload = body.json()
    assert payload["failed_fields"] == []
    assert payload["matches"]["list.item"] > 1
    assert payload["usage"]["model"] == "gemini-3.5-flash"
    assert payload["usage"]["input_tokens"] == 10399
    assert payload["name"] == "www.python.org"


def test_failed_field_is_surfaced_but_the_draft_is_kept(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """실패한 필드가 있어도 행은 남는다. 그 필드만 손으로 고치는 것이 첫 수단이다."""
    broken = json.loads(json.dumps(GENERATED))
    broken["list"]["date"] = "span.published-on"
    use_generator(result_for(broken))

    response = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    assert response.json()["failed_fields"] == ["list.date"]
    assert rows(conn)[0]["status"] == "draft"


def test_robots_disallow_refuses_registration(client: TestClient, conn: sqlite3.Connection) -> None:
    use_generator(RobotsDisallowedError("robots.txt 가 막은 경로다"))

    response = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "robots"
    assert rows(conn) == []


def test_transport_failure_leaves_no_row(client: TestClient, conn: sqlite3.Connection) -> None:
    use_generator(TransportError("전송 실패"))

    response = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    assert response.status_code == 502
    assert response.json()["detail"]["reason"] == "transport"
    assert rows(conn) == []


def test_missing_api_key_is_a_server_side_reason(client: TestClient) -> None:
    use_generator(SelectorGenerationError("no_api_key", "GEMINI_API_KEY 가 비어 있다"))

    response = client.post("/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL})

    assert response.status_code == 500
    assert response.json()["detail"]["reason"] == "no_api_key"


def test_manual_edit_changes_selectors_and_keeps_status(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    use_generator(result_for(GENERATED))
    created = client.post(
        "/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL}
    ).json()
    conn.execute("UPDATE crawlers SET status = 'tested' WHERE id = ?", (created["id"],))

    edited = json.loads(json.dumps(GENERATED))
    edited["list"]["date"] = "time[datetime]"
    response = client.put(f"/api/crawlers/{created['id']}/selectors", json=edited)

    assert response.status_code == 200
    saved = rows(conn)[0]
    assert json.loads(saved["selectors_json"])["list"]["date"] == "time[datetime]"
    assert saved["status"] == "tested"
    assert response.json()["status"] == "tested"


def test_manual_edit_does_not_regenerate(client: TestClient, conn: sqlite3.Connection) -> None:
    """편집된 셀렉터를 요청 없이 다시 생성하지 않는다 (rules/llm.md)."""
    use_generator(result_for(GENERATED))
    created = client.post(
        "/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL}
    ).json()
    use_generator(AssertionError("수동 보정은 생성을 부르지 않는다"))

    response = client.put(f"/api/crawlers/{created['id']}/selectors", json=GENERATED)

    assert response.status_code == 200


def test_manual_edit_rejects_a_field_the_schema_does_not_have(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    use_generator(result_for(GENERATED))
    created = client.post(
        "/api/crawlers", json={"list_url": LIST_URL, "detail_url": DETAIL_URL}
    ).json()

    broken = json.loads(json.dumps(GENERATED))
    broken["list"]["links"] = "a"
    response = client.put(f"/api/crawlers/{created['id']}/selectors", json=broken)

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unknown_field"
    assert json.loads(rows(conn)[0]["selectors_json"]) == GENERATED


def test_manual_edit_on_a_missing_crawler_is_404(client: TestClient) -> None:
    response = client.put("/api/crawlers/999/selectors", json=GENERATED)

    assert response.status_code == 404
