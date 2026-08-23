"""재시도 정책 테스트.

`transport` 만 재시도한다. `selector_miss` 는 재시도하지 않는다 — 페이지는 이미 정상으로
왔고, 4초 뒤에 다시 물어도 같은 HTML 이 온다. 재시도해봐야 이미 답한 사이트의 부하만 두 배가
된다 (`.claude/rules/crawling.md`).

응답은 전부 `httpx.MockTransport` 스텁이고 시간은 가짜라 실제로 기다리는 구간이 없다. 목록
HTML 은 저장된 python.org 픽스처를 그대로 돌려준다.
"""

from __future__ import annotations

import pathlib

import httpx
import pytest

from app.config import Settings
from app.crawler.fetcher import Fetcher, TransportError
from app.crawler.parser import SelectorMissError, parse_list
from app.selector.schema import ListSelectors

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LIST_HTML = (FIXTURES / "pythonorg-jobs-list-20260821.html").read_text(encoding="utf-8")
LIST_URL = "https://www.python.org/jobs/"
ROBOTS = "User-agent: *\nDisallow:\n"

MISSING_ITEM = ListSelectors(
    item="ol.list-of-nothing > li",
    title="span.listing-company-name > a",
    link="span.listing-company-name > a",
    date="span.listing-posted time",
)


class StubSite:
    """요청 수를 세는 스텁. 대상 URL 요청만 센다 — robots.txt 는 정책과 무관하다."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self._response = response
        self.requests: list[str] = []
        self.sleeps: list[float] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        self.requests.append(str(request.url))
        if self._response is None:
            return httpx.Response(200, text=LIST_HTML)
        return httpx.Response(self._response.status_code, text=self._response.text)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def fetcher(self, max_retries: int) -> Fetcher:
        return Fetcher(
            settings=Settings(crawl_delay_seconds=0.0, crawl_max_retries=max_retries),
            transport=self.transport,
            sleep=self.sleep,
        )


@pytest.mark.parametrize("max_retries", [2, 3])
async def test_5xx_는_상한까지_다시_요청한다(max_retries: int) -> None:
    """요청 횟수는 최초 1회 + `CRAWL_MAX_RETRIES` 회다. 상한 2면 3회, 3이면 4회다."""
    site = StubSite(httpx.Response(503))
    fetcher = site.fetcher(max_retries)

    with pytest.raises(TransportError):
        await fetcher.fetch(LIST_URL)
    await fetcher.aclose()

    assert len(site.requests) == 1 + max_retries
    # 그냥 다시 부르는 것이 아니라 간격을 늘려가며 부른다.
    assert site.sleeps == [1.0 * 2**attempt for attempt in range(max_retries)]


async def test_셀렉터_미스는_다시_요청하지_않는다() -> None:
    """200 으로 받은 뒤의 0개 매칭이다. 같은 페이지를 다시 부르지 않는다."""
    site = StubSite()
    fetcher = site.fetcher(max_retries=3)

    result = await fetcher.fetch(LIST_URL)
    with pytest.raises(SelectorMissError):
        parse_list(result.text, MISSING_ITEM, LIST_URL)
    await fetcher.aclose()

    assert len(site.requests) == 1
    assert site.sleeps == []
