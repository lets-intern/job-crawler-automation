"""크롤러 등록 화면의 AI 수정 버튼 (17.3).

확인하는 것.

- 실패한 필드가 있을 때만 버튼이 보인다. 없으면 고칠 것이 없다
- 결과는 전/후 비교와 새 셀렉터 JSON 이고, 저장은 기존 "셀렉터 저장" 을 그대로 쓴다
- 누르는 것만으로 `crawlers.selectors_json` 이 바뀌지 않는다
- 실패하면 사유가 화면에 남는다. Gemini 한도 초과(429)도 그대로 보인다

Gemini 도 실사이트도 부르지 않는다. 화면이 실제로 뜨는지는 17.3.V 가 로컬에서 따로 본다.
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
from app.main import app
from app.selector.generator import SelectorGenerationError
from app.selector.schema import SelectorSet
from tests.test_api_selector_repair import (
    FIXED,
    insert_crawler,
    outcome_for,
    stored_selectors,
)
from tests.test_selector_repair import BROKEN


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


def use_repairer(result: Any) -> list[str]:
    """고치기 의존성을 갈아끼우고, 화면이 실어 보낸 힌트를 기록한다."""
    hints: list[str] = []

    async def repair(
        list_url: str,
        detail_url: str,
        render_mode: str,
        selectors: SelectorSet,
        *,
        hint: str = "",
    ) -> Any:
        hints.append(hint)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result(selectors)
        return result

    app.dependency_overrides[crawlers_api.get_repairer] = lambda: repair
    return hints


# 버튼 ----------------------------------------------------------------------


def test_the_button_stays_after_everything_was_fixed(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """이번 고치기로 전부 해결됐다. 그래도 버튼은 남는다 — 잡히는 값이 틀렸는데 고칠 길이
    없으면 운영자가 막힌다. 대신 고칠 것이 없다는 사실과 다음 수를 그 자리에 적는다."""
    crawler_id = insert_crawler(conn)
    use_repairer(outcome_for)

    body = client.post(f"/ui/crawlers/{crawler_id}/repair").text

    assert f'hx-post="/ui/crawlers/{crawler_id}/repair"' in body
    assert "지금 실패한 필드는 없다" in body
    assert "힌트에 적으면 그 필드를 고친다" in body


def test_the_button_stays_when_a_field_is_still_failing(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = insert_crawler(conn)
    still_wrong = json.loads(json.dumps(BROKEN))
    still_wrong["list"]["item"] = "nav.family ul li"
    use_repairer(lambda selectors: outcome_for(selectors, still_wrong))

    body = client.post(f"/ui/crawlers/{crawler_id}/repair").text

    assert f'hx-post="/ui/crawlers/{crawler_id}/repair"' in body
    assert "고친 뒤에도 실패로 남은 필드" in body


def test_the_editor_alone_has_no_button(client: TestClient, conn: sqlite3.Connection) -> None:
    """편집기만 열었을 때는 무엇이 실패인지 판정한 적이 없다. 버튼을 내밀지 않는다."""
    crawler_id = insert_crawler(conn)

    body = client.get(f"/ui/crawlers/{crawler_id}/editor").text

    assert f'hx-post="/ui/crawlers/{crawler_id}/repair"' not in body
    assert "셀렉터 저장" in body


def test_the_button_locks_while_it_runs(client: TestClient, conn: sqlite3.Connection) -> None:
    """생성과 같은 시간이 걸린다. 누른 뒤 아무 변화가 없으면 눌렸는지 알 수 없다."""
    crawler_id = insert_crawler(conn)
    still_wrong = json.loads(json.dumps(BROKEN))
    still_wrong["list"]["item"] = "nav.family ul li"
    use_repairer(lambda selectors: outcome_for(selectors, still_wrong))

    body = client.post(f"/ui/crawlers/{crawler_id}/repair").text

    assert 'hx-disabled-elt="find button"' in body
    assert 'hx-indicator="#repair-wait, #crawler-result-wait"' in body
    assert 'id="repair-wait"' in body


# 결과 ----------------------------------------------------------------------


def test_before_and_after_are_shown_side_by_side(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = insert_crawler(conn)
    use_repairer(outcome_for)

    body = client.post(f"/ui/crawlers/{crawler_id}/repair").text

    assert "고치기 전과 후" in body
    assert "바뀐 셀렉터" not in body or "ul.family-group li" in body
    # 고친 셀렉터가 편집기에 올라간다. 저장은 아직이다
    assert "ul.job-card-list &gt; li.job-card" in body
    assert "아직 저장하지 않았다" in body
    assert "셀렉터 저장" in body


def test_pressing_the_button_does_not_touch_the_database(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = insert_crawler(conn)
    before = stored_selectors(conn, crawler_id)
    use_repairer(outcome_for)

    client.post(f"/ui/crawlers/{crawler_id}/repair")

    assert stored_selectors(conn, crawler_id) == before


def test_the_save_button_is_what_writes_it(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = insert_crawler(conn)
    use_repairer(outcome_for)
    client.post(f"/ui/crawlers/{crawler_id}/repair")

    saved = client.put(
        f"/ui/crawlers/{crawler_id}/selectors",
        data={"selectors_json": json.dumps(FIXED, ensure_ascii=False)},
    )

    assert saved.status_code == 200
    assert stored_selectors(conn, crawler_id)["list"]["item"] == "ul.job-card-list > li.job-card"


def test_no_icons_or_emoji_in_the_result(client: TestClient, conn: sqlite3.Connection) -> None:
    """판정은 단어로 적는다 (`../.claude/rules/writing.md`)."""
    crawler_id = insert_crawler(conn)
    use_repairer(outcome_for)

    body = client.post(f"/ui/crawlers/{crawler_id}/repair").text

    pictograms = [
        ch
        for ch in body
        if 0x2190 <= ord(ch) <= 0x2BFF or 0x1F300 <= ord(ch) <= 0x1FAFF or ord(ch) == 0xFE0F
    ]
    assert pictograms == []
    assert "고침" in body
    assert "그대로" in body


# 실패 ----------------------------------------------------------------------


def test_a_rate_limit_is_shown_on_screen(client: TestClient, conn: sqlite3.Connection) -> None:
    """Gemini 무료 한도는 분당 20회다. 429 를 화면에서 읽을 수 있어야 한다."""
    crawler_id = insert_crawler(conn)
    use_repairer(SelectorGenerationError("api_error", "Gemini 호출 실패(429): RESOURCE_EXHAUSTED"))

    response = client.post(f"/ui/crawlers/{crawler_id}/repair")

    # HTMX 는 4xx 를 갈아 끼우지 않는다. 조각은 200 으로 사유를 실어 나른다
    assert response.status_code == 200
    assert "429" in response.text
    assert "api_error" in response.text
    # 실패해도 편집기는 남는다. 손으로 고칠 자리를 잃지 않는다
    assert "셀렉터 저장" in response.text
    assert "ul.family-group li" in response.text


def test_a_failed_repair_leaves_the_stored_selectors_alone(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = insert_crawler(conn)
    before = stored_selectors(conn, crawler_id)
    use_repairer(SelectorGenerationError("api_error", "Gemini 호출 실패(429): 한도 초과"))

    client.post(f"/ui/crawlers/{crawler_id}/repair")

    assert stored_selectors(conn, crawler_id) == before


def test_an_unknown_crawler_says_so(client: TestClient) -> None:
    use_repairer(outcome_for)

    response = client.post("/ui/crawlers/9999/repair")

    assert response.status_code == 200
    assert "9999" in response.text


# 힌트 입력 (20.3) -----------------------------------------------------------


def test_the_repair_form_has_the_same_hint_box_as_the_test_screen(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """두 화면이 같은 매크로를 쓴다. 한쪽에만 설명이 붙는 일이 없어야 한다."""
    crawler_id = insert_crawler(conn)
    still_wrong = json.loads(json.dumps(BROKEN))
    still_wrong["list"]["item"] = "nav.family ul li"
    use_repairer(lambda selectors: outcome_for(selectors, still_wrong))

    body = client.post(f"/ui/crawlers/{crawler_id}/repair").text

    assert 'name="hint"' in body
    assert "Copy selector" in body
    assert "그대로 저장되지는 않는다" in body


def test_the_hint_reaches_the_repairer(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = insert_crawler(conn)
    hints = use_repairer(outcome_for)
    hint = "#root > div > main > div.MuiBox-root.css-1jelp97 > div:nth-child(2) > div"

    client.post(f"/ui/crawlers/{crawler_id}/repair", data={"hint": hint})

    assert hints == [hint]


def test_the_repair_still_works_without_a_hint(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = insert_crawler(conn)
    hints = use_repairer(outcome_for)

    response = client.post(f"/ui/crawlers/{crawler_id}/repair")

    assert response.status_code == 200
    assert hints == [""]
