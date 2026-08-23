"""테스트 실행 화면의 AI 수정 (20.2).

실패는 주기 실행에서 나고 확인은 이 화면에서 한다. 고치는 수단이 등록 화면에만 있으면
운영자는 방금 본 실패를 두고 화면을 옮겨야 한다.

확인하는 것.

- 실패한 필드가 있는 실행에만 수정 자리가 붙는다. 다 성공한 실행에는 고칠 것이 없다
- 힌트 입력칸이 함께 있고, 넣은 값이 고치기 경로까지 간다
- 고친 결과는 전/후 매칭 수와 새 셀렉터고, **누르는 것만으로 저장되지 않는다**
- 저장은 이 화면의 버튼이 하고, 저장한 뒤에도 자리를 옮기지 않는다 — 같은 자리에서
  바로 다시 실행할 수 있다

Gemini 도 실사이트도 부르지 않는다. fetch 는 python.org 픽스처를 돌려주는 스텁이고
고치기는 의존성을 갈아끼운다.
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
from app.selector.repair import RepairOutcome
from app.selector.schema import SelectorSet, validate_selectors
from app.selector.verify import verify_selectors
from tests.test_api_selector_repair import USAGE
from tests.test_api_test_run import LIST_URL, SELECTORS, stub_fetcher


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
    """fetch 는 python.org 픽스처를 돌려주는 스텁이다. 실사이트에 나가지 않는다."""

    def request_connection() -> Iterator[sqlite3.Connection]:
        connection = db.connect(tmp_path / "jobs.db")
        try:
            yield connection
        finally:
            connection.close()

    fetcher = stub_fetcher()
    app.dependency_overrides[crawlers_api.get_connection] = request_connection
    app.dependency_overrides[crawlers_api.get_crawl_fetcher] = lambda: fetcher
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LIST_HTML = (FIXTURES / "pythonorg-jobs-list-20260821.html").read_text(encoding="utf-8")

HINT = (
    "#root > div > div > main > div > div.MuiBox-root.css-jj9lbc > div > div > "
    "div.MuiBox-root.css-1jelp97 > div:nth-child(2) > div"
)


def broken(**list_fields: str) -> dict[str, Any]:
    """python.org 셀렉터에서 목록 필드 몇 개만 망가뜨린다."""
    payload = json.loads(json.dumps(SELECTORS))
    payload["list"].update(list_fields)
    return payload


def add_crawler(conn: sqlite3.Connection, selectors: dict[str, Any]) -> int:
    cursor = conn.execute(
        """
        INSERT INTO crawlers (name, list_url, detail_url, selectors_json, status, render_mode)
        VALUES ('python.org', ?, 'https://www.python.org/jobs/8126/', ?, 'draft', 'static')
        """,
        (LIST_URL, json.dumps(selectors)),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def outcome(before: dict[str, Any], after: dict[str, Any]) -> RepairOutcome:
    """실제 고치기와 같은 계산을 픽스처로 만든다. 모델 응답만 정해 준다."""
    from app.selector.repair import SelectorChange, repair_targets

    original = validate_selectors(before)
    repaired = validate_selectors(after)
    first = verify_selectors(original, LIST_HTML, "")
    targets = repair_targets(first, has_detail_html=False)
    second = verify_selectors(repaired, LIST_HTML, "")
    remaining = set(repair_targets(second, has_detail_html=False))
    changes = [
        SelectorChange(
            name=f"list.{name}",
            before=str(before["list"].get(name, "")),
            after=str(after["list"].get(name, "")),
        )
        for name in before["list"]
        if before["list"].get(name) != after["list"].get(name)
    ]
    return RepairOutcome(
        selectors=repaired,
        before=first,
        after=second,
        usage=USAGE,
        attempts=1,
        targets=targets,
        failed_targets=targets,
        changes=changes,
        unresolved=[name for name in targets if name in remaining],
    )


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
    ) -> RepairOutcome:
        hints.append(hint)
        if isinstance(result, Exception):
            raise result
        return result

    app.dependency_overrides[crawlers_api.get_repairer] = lambda: repair
    return hints


def stored(conn: sqlite3.Connection, crawler_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT selectors_json FROM crawlers WHERE id = ?", (crawler_id,)).fetchone()
    return dict(json.loads(row["selectors_json"]))


# 수정 자리가 나오는 조건 -----------------------------------------------------


def test_a_failing_run_shows_the_repair_form(client: TestClient, conn: sqlite3.Connection) -> None:
    """등록일을 못 읽는 크롤러. 결과 아래에 고칠 수단이 함께 나온다."""
    crawler_id = add_crawler(conn, broken(date="span.does-not-exist"))

    body = client.post(f"/ui/crawlers/{crawler_id}/test-run", data={"limit": "1"}).text

    assert 'id="test-repair"' in body
    assert f'hx-post="/ui/tests/{crawler_id}/repair"' in body
    assert "list.date" in body


def test_a_clean_run_still_offers_the_button(client: TestClient, conn: sqlite3.Connection) -> None:
    """실행이 성공이어도 잡히는 값이 틀릴 수 있다. 고칠 길이 없으면 운영자가 막힌다."""
    crawler_id = add_crawler(conn, SELECTORS)

    body = client.post(f"/ui/crawlers/{crawler_id}/test-run", data={"limit": "1"}).text

    assert f'hx-post="/ui/tests/{crawler_id}/repair"' in body
    # 고칠 대상이 없다는 것과 무엇을 하면 되는지를 그 자리에 적는다
    assert "이번 실행의 필드 표에는 실패가 없다" in body
    assert "힌트에 적으면 그 필드를 고친다" in body


def test_a_clean_run_with_no_hint_says_there_is_nothing_to_repair(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """힌트도 실패도 없으면 모델을 부르지 않는다. 대신 무엇을 하면 되는지 적는다."""
    from app.selector.repair import SelectorRepairError

    crawler_id = add_crawler(conn, SELECTORS)
    use_repairer(
        SelectorRepairError(
            "nothing_to_repair",
            "실패한 필드가 없다. 어느 필드가 무엇을 잘못 잡는지 힌트에 적으면 그 필드를 고친다",
        )
    )

    body = client.post(f"/ui/tests/{crawler_id}/repair").text

    assert "힌트에 적으면 그 필드를 고친다" in body
    assert 'name="hint"' in body


def test_a_run_that_matched_nothing_still_offers_the_repair(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """항목을 하나도 못 잡으면 필드 표는 빈 줄만 남는다. 그래도 고칠 것은 있다."""
    crawler_id = add_crawler(conn, broken(item="ol.gone > li"))

    body = client.post(f"/ui/crawlers/{crawler_id}/test-run", data={"limit": "1"}).text

    assert f'hx-post="/ui/tests/{crawler_id}/repair"' in body


# 힌트 -----------------------------------------------------------------------


def test_the_form_has_a_hint_box_that_says_what_to_put_in_it(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = add_crawler(conn, broken(date="span.does-not-exist"))

    body = client.post(f"/ui/crawlers/{crawler_id}/test-run", data={"limit": "1"}).text

    assert 'name="hint"' in body
    assert "Copy selector" in body
    # 그대로 저장되지 않는다는 것을 화면에서 말한다
    assert "그대로 저장되지는 않는다" in body


def test_the_hint_reaches_the_repairer(client: TestClient, conn: sqlite3.Connection) -> None:
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    hints = use_repairer(outcome(before, SELECTORS))

    client.post(f"/ui/tests/{crawler_id}/repair", data={"hint": HINT})

    assert hints == [HINT]


def test_the_repair_works_without_a_hint(client: TestClient, conn: sqlite3.Connection) -> None:
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    hints = use_repairer(outcome(before, SELECTORS))

    response = client.post(f"/ui/tests/{crawler_id}/repair")

    assert response.status_code == 200
    assert hints == [""]


# 전/후와 저장 ---------------------------------------------------------------


def test_before_and_after_are_shown_side_by_side(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    use_repairer(outcome(before, SELECTORS))

    body = client.post(f"/ui/tests/{crawler_id}/repair").text

    assert "고치기 전과 후" in body
    assert "바뀐 셀렉터" in body
    assert "span.listing-posted time" in body


def test_pressing_repair_does_not_touch_the_database(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """저장은 운영자가 누른다 (`.claude/rules/llm.md`)."""
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    use_repairer(outcome(before, SELECTORS))

    body = client.post(f"/ui/tests/{crawler_id}/repair").text

    assert stored(conn, crawler_id)["list"]["date"] == "span.does-not-exist"
    assert "아직 저장하지 않았다" in body


def test_the_save_button_on_this_screen_writes_it(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    crawler_id = add_crawler(conn, broken(date="span.does-not-exist"))

    response = client.put(
        f"/ui/tests/{crawler_id}/selectors",
        data={"selectors_json": json.dumps(SELECTORS)},
    )

    assert response.status_code == 200
    assert stored(conn, crawler_id)["list"]["date"] == "span.listing-posted time"


def test_after_saving_the_run_button_is_right_there(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """화면을 옮기지 않는다. 방금 저장한 셀렉터를 그 자리에서 다시 돌린다."""
    crawler_id = add_crawler(conn, broken(date="span.does-not-exist"))

    body = client.put(
        f"/ui/tests/{crawler_id}/selectors",
        data={"selectors_json": json.dumps(SELECTORS)},
    ).text

    assert "저장했다" in body
    assert f'hx-post="/ui/crawlers/{crawler_id}/test-run"' in body
    assert 'hx-target="#test-result"' in body


def test_a_rejected_save_keeps_what_was_typed(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = add_crawler(conn, broken(date="span.does-not-exist"))

    body = client.put(
        f"/ui/tests/{crawler_id}/selectors", data={"selectors_json": "{셀렉터 아님"}
    ).text

    assert "JSON 으로 읽을 수 없다" in body
    assert "{셀렉터 아님" in body
    assert stored(conn, crawler_id)["list"]["date"] == "span.does-not-exist"


# 실패 -----------------------------------------------------------------------


def test_a_rate_limit_is_shown_on_screen(client: TestClient, conn: sqlite3.Connection) -> None:
    crawler_id = add_crawler(conn, broken(date="span.does-not-exist"))
    use_repairer(SelectorGenerationError("api_error", "429 RESOURCE_EXHAUSTED: 분당 한도 초과"))

    body = client.post(f"/ui/tests/{crawler_id}/repair").text

    assert "429" in body
    assert "api_error" in body
    # 못 고쳤다고 손으로 고칠 자리까지 사라지면 안 된다
    assert 'name="selectors_json"' in body


def test_no_icons_or_emoji_in_the_panel(client: TestClient, conn: sqlite3.Connection) -> None:
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    use_repairer(outcome(before, SELECTORS))

    body = client.post(f"/ui/tests/{crawler_id}/repair").text

    for glyph in ("✅", "❌", "⚠", "⭐", "\U0001f4dd", "✔", "✖"):
        assert glyph not in body


def test_the_editor_and_the_repair_share_one_place(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    """고치기·저장·다시 실행이 한 조각 안에 있다. 화면을 옮길 일이 없다."""
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    use_repairer(outcome(before, SELECTORS))

    body = client.post(f"/ui/tests/{crawler_id}/repair").text

    assert f'hx-post="/ui/tests/{crawler_id}/repair"' in body
    assert f'hx-put="/ui/tests/{crawler_id}/selectors"' in body
    assert f'hx-post="/ui/crawlers/{crawler_id}/test-run"' in body


def test_db_is_untouched_until_the_save(client: TestClient, conn: sqlite3.Connection) -> None:
    """고친 셀렉터는 편집기에만 올라간다. 저장을 눌러야 DB 가 바뀐다."""
    before = broken(date="span.does-not-exist")
    crawler_id = add_crawler(conn, before)
    use_repairer(outcome(before, SELECTORS))

    body = client.post(f"/ui/tests/{crawler_id}/repair").text
    assert stored(conn, crawler_id)["list"]["date"] == "span.does-not-exist"

    assert "span.listing-posted time" in body
    client.put(f"/ui/tests/{crawler_id}/selectors", data={"selectors_json": json.dumps(SELECTORS)})
    assert stored(conn, crawler_id)["list"]["date"] == "span.listing-posted time"
