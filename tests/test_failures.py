"""실패 분류 테스트.

세 가지 실패가 각각 다른 `error_class` 로 끝나는지 본다. 실사이트에 나가지 않는다 — 전송 실패는
`httpx.MockTransport` 스텁이고, 나머지 둘은 저장된 python.org HTML 에 어긋난 셀렉터를 적용해
만든다.
"""

from __future__ import annotations

import pathlib

import httpx
import pytest

from app.config import Settings
from app.crawler.failures import FAILED, SUCCESS, classify, run_status
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
