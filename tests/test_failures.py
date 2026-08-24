"""실패 분류 테스트.

세 가지 실패가 각각 다른 `error_class` 로 끝나는지 본다. 실사이트에 나가지 않는다 — 전송 실패는
`httpx.MockTransport` 스텁이고, 나머지 둘은 저장된 python.org HTML 에 어긋난 셀렉터를 적용해
만든다.

사유 목록 자체도 여기서 본다. `ERROR_CLASSES` 와 `crawl_run_failures.reason` 의 CHECK,
운영자에게 보일 다음 행동(`NEXT_STEPS`)이 셋 다 같은 값을 알고 있어야 한다.
"""

from __future__ import annotations

import pathlib
import sqlite3
from collections.abc import Iterator

import httpx
import pytest

from app import db
from app.api.ui import NEXT_STEPS
from app.config import Settings
from app.crawler.failures import ERROR_CLASSES, FAILED, SUCCESS, classify, run_status
from app.crawler.fetcher import Fetcher
from app.crawler.parser import parse_list
from app.selector.schema import ListSelectors

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LIST_HTML = (FIXTURES / "pythonorg-jobs-list-20260821.html").read_text(encoding="utf-8")
LIST_URL = "https://www.python.org/jobs/"

WORKING = ListSelectors(
    item="ol.list-recent-jobs > li",
    title="span.listing-company-name > a",
    link="span.listing-company-name > a",
    date="span.listing-posted time",
)


def replaced(**changes: str) -> ListSelectors:
    return ListSelectors(**{**WORKING.model_dump(), **changes})


async def fetch_failure() -> Exception:
    """5xx 만 돌려주는 스텁 사이트에서 재시도를 다 쓰고 올라온 예외."""

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        return httpx.Response(503)

    async def no_wait(seconds: float) -> None:
        return None

    fetcher = Fetcher(
        settings=Settings(crawl_delay_seconds=0.0, crawl_max_retries=1),
        transport=httpx.MockTransport(responder),
        sleep=no_wait,
    )
    try:
        with pytest.raises(Exception) as caught:  # noqa: PT011 - 분류 대상이 예외 그 자체다
            await fetcher.fetch(LIST_URL)
    finally:
        await fetcher.aclose()
    return caught.value


async def test_전송_실패는_transport_다() -> None:
    failure = classify(await fetch_failure())

    assert failure.error_class == "transport"
    assert "503" in failure.message


def test_item_0개_매칭은_selector_miss_이고_실행은_실패로_끝난다() -> None:
    with pytest.raises(Exception) as caught:  # noqa: PT011 - 분류 대상이 예외 그 자체다
        parse_list(LIST_HTML, replaced(item="ol.list-of-nothing > li"), LIST_URL)

    failure = classify(caught.value)
    assert failure.error_class == "selector_miss"
    # 가져오기는 200 으로 성공했지만 신규 0건인 정상 실행이 아니다.
    assert run_status(0, failure) == FAILED


def test_매칭_뒤_필드를_못_읽으면_parse_다() -> None:
    with pytest.raises(Exception) as caught:  # noqa: PT011 - 분류 대상이 예외 그 자체다
        parse_list(LIST_HTML, replaced(link="a.does-not-exist"), LIST_URL)

    assert classify(caught.value).error_class == "parse"


def test_모르는_예외는_error_class_없이_남는다() -> None:
    """추측해서 세 값 중 하나로 밀어 넣지 않는다."""
    failure = classify(RuntimeError("무엇인가 잘못됐다"))

    assert failure.error_class is None
    assert "RuntimeError" in failure.message


def test_아이템_0건은_실패다() -> None:
    """가져오기도 파싱도 예외 없이 끝났더라도 정상 항목이 0건이면 실패다."""
    assert run_status(0) == FAILED
    assert run_status(0, None) == FAILED


def test_정상_항목이_있고_실패가_없으면_성공이다() -> None:
    assert run_status(25) == SUCCESS


def test_실패가_있으면_정상_항목이_있어도_실패다() -> None:
    failure = classify(RuntimeError("중간에 끊겼다"))

    assert run_status(3, failure) == FAILED


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    connection = db.connect(tmp_path / "failures.db")
    db.migrate_up(connection)
    yield connection
    connection.close()


def _run(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO crawlers (name, list_url) VALUES (?, ?)", ("테스트", "https://example.test")
    )
    connection.execute("INSERT INTO crawl_runs (crawler_id) VALUES (1)")


@pytest.mark.parametrize("error_class", ERROR_CLASSES)
def test_사유마다_운영자가_할_다음_행동이_있다(error_class: str) -> None:
    """사유를 늘리면서 문구를 안 적으면 화면은 사유만 적고 조치를 말하지 못한다."""
    assert NEXT_STEPS[error_class].strip()


@pytest.mark.parametrize("error_class", ERROR_CLASSES)
def test_실패_목록이_모든_사유를_받는다(conn: sqlite3.Connection, error_class: str) -> None:
    """`crawl_run_failures.reason` 의 CHECK 는 `ERROR_CLASSES` 와 같은 값이어야 한다."""
    _run(conn)

    conn.execute("INSERT INTO crawl_run_failures (run_id, reason) VALUES (1, ?)", (error_class,))

    row = conn.execute("SELECT reason FROM crawl_run_failures").fetchone()
    assert row["reason"] == error_class


def test_분류하지_못한_실패는_사유_없이_남는다(conn: sqlite3.Connection) -> None:
    """모르는 실패를 아는 실패로 위장하지 않는다. 사유는 NULL 이고 내용만 남는다."""
    _run(conn)

    conn.execute(
        """
        INSERT INTO crawl_run_failures (run_id, reason, message)
        VALUES (1, NULL, '분류되지 않은 실패(RuntimeError)')
        """
    )

    row = conn.execute("SELECT reason, message FROM crawl_run_failures").fetchone()
    assert row["reason"] is None
    assert "RuntimeError" in row["message"]


@pytest.mark.parametrize("reason", ["detail_missing", "unknown", "timeout", ""])
def test_실패_목록이_ERROR_CLASSES_밖의_사유를_거절한다(
    conn: sqlite3.Connection, reason: str
) -> None:
    _run(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO crawl_run_failures (run_id, reason) VALUES (1, ?)", (reason,))
