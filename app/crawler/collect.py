"""실행 하나가 목록과 상세를 무엇으로 가져올지 고르는 자리.

`crawlers.list_mode` 와 `detail_mode` 가 각각 `static` / `api` / `playwright` 중 하나다.
**섞어 쓰는 것이 정상적인 선택지다** — 목록이 JSON API 로 오고 상세는 브라우저가 있어야
그려지는 사이트가 있고, 하나의 값으로는 그 사이트를 담을 수 없다.

여기서 고른 뒤로는 러너가 같은 코드를 돈다. 수집기는 둘 다 같은 것을 돌려준다.

| 수집기 | 돌려주는 것 |
|---|---|
| `ListCollector.collect()` | `ListParseResult` |
| `DetailCollector.collect(item)` | `DetailParseResult` |

## 브라우저는 실제로 필요한 쪽에서만 뜬다

`open_collectors()` 가 브라우저의 수명을 들고 있다. 목록이 `api` 면 목록 때문에 브라우저가
뜨지 않고, 상세만 `playwright` 면 상세를 가져올 때 하나가 뜬다. 양쪽이 다 `playwright` 면
브라우저 하나를 나눠 쓴다 — 인스턴스 하나가 150~300MB 다 (`.claude/rules/crawling.md`).

셀렉터 생성과 AI 수정은 아직 `app/crawler/playwright.py` 의 `open_source()` 를 쓴다. 그쪽은
HTML 한 장을 가져오는 일이라 목록·상세를 나눌 자리가 없다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.crawler import playwright as render_module
from app.crawler.api_source import fetch_detail, fetch_list
from app.crawler.fetcher import FetchPolicy, PageSource
from app.crawler.parser import (
    DetailParseResult,
    FieldParseError,
    ListItem,
    ListParseResult,
    SelectorMissError,
    parse_detail,
    parse_list,
)
from app.crawler.playwright import PLAYWRIGHT, STATIC, Renderer
from app.crawler.shell import promotion_hint
from app.selector.api_schema import ApiConfig
from app.selector.schema import DetailSelectors, ListSelectors, SelectorSet

logger = logging.getLogger(__name__)

API = "api"
# `crawlers.list_mode` 와 `detail_mode` 의 CHECK 제약과 같은 값이어야 한다
COLLECT_MODES: tuple[str, ...] = (STATIC, API, PLAYWRIGHT)


class ListCollector(Protocol):
    async def collect(self) -> ListParseResult: ...


class DetailCollector(Protocol):
    async def collect(self, item: ListItem) -> DetailParseResult: ...


@dataclass(frozen=True)
class Collectors:
    """이 실행이 쓸 두 수집기. 모드는 실패 사유에 적으려고 함께 들고 있다."""

    list_mode: str
    detail_mode: str
    list: ListCollector
    detail: DetailCollector


class HtmlListCollector:
    """HTML 목록. 정적 fetch 와 렌더가 같은 코드를 쓰고 `source` 만 다르다."""

    def __init__(
        self, source: PageSource, list_url: str, selectors: ListSelectors, mode: str
    ) -> None:
        self._source = source
        self._list_url = list_url
        self._selectors = selectors
        self._mode = mode

    async def collect(self) -> ListParseResult:
        page = await self._source.fetch(self._list_url)
        try:
            return parse_list(page.text, self._selectors, page.url)
        except SelectorMissError as exc:
            # 0개 매칭이 마크업 변경인지 JS 렌더인지를 사유에 적는다. 승격은 운영자가 정하므로
            # 여기서 모드를 바꾸지 않는다 (`app/crawler/shell.py`)
            hint = promotion_hint(page.text, self._mode)
            if hint is None:
                raise
            raise SelectorMissError(f"{exc}. {hint}") from exc


class HtmlDetailCollector:
    """HTML 상세. 항목의 링크를 그대로 따라간다."""

    def __init__(self, source: PageSource, selectors: DetailSelectors) -> None:
        self._source = source
        self._selectors = selectors

    async def collect(self, item: ListItem) -> DetailParseResult:
        page = await self._source.fetch(item.link)
        return parse_detail(page.text, self._selectors)


class ApiListCollector:
    """JSON 목록. 요청은 공용 fetch 클라이언트로 나간다."""

    def __init__(self, client: FetchPolicy, config: ApiConfig) -> None:
        self._client = client
        self._config = config.list_config()

    async def collect(self) -> ListParseResult:
        return await fetch_list(self._client, self._config)


class ApiDetailCollector:
    """JSON 상세. 공고 id 로 한 건을 지목해 가져온다.

    id 는 목록이 API 면 응답에서 그대로 오고(`ListItem.detail_key`), 목록이 HTML 이면 상세
    링크의 마지막 경로 조각을 쓴다. 그것도 없으면 무엇을 물어볼지 알 수 없으므로 실패다 —
    아무 값이나 넣어 엉뚱한 공고를 가져오지 않는다.
    """

    def __init__(self, client: FetchPolicy, config: ApiConfig) -> None:
        self._client = client
        self._config = config.detail_config()

    async def collect(self, item: ListItem) -> DetailParseResult:
        item_id = item.detail_key or _id_from_link(item.link)
        if not item_id:
            raise FieldParseError(
                f"상세 API 에 넘길 id 를 찾지 못했다: {item.link}. "
                "목록을 `api` 로 두거나 링크 마지막 조각이 id 인 사이트여야 한다"
            )
        return await fetch_detail(self._client, self._config, item_id)


@asynccontextmanager
async def open_collectors(
    *,
    list_mode: str,
    detail_mode: str,
    list_url: str,
    selectors: SelectorSet,
    fetcher: FetchPolicy,
    api_config: ApiConfig | None = None,
    renderer: Callable[[FetchPolicy], Renderer] | None = None,
) -> AsyncIterator[Collectors]:
    """이 실행이 쓸 수집기 둘을 만든다. 브라우저 수명이 이 블록이다.

    모르는 모드는 정적이다. 렌더도 API 도 운영자가 명시적으로 올린 사이트만 받는다.
    """
    # 모듈을 통해 부른다. 렌더러를 대역으로 바꿔 끼우는 시험이 `open_source()` 와 같은 자리를
    # 본다 — 브라우저가 뜨는 경로가 둘로 갈리면 어느 쪽이 막혔는지 알 수 없다
    build = renderer or (lambda client: render_module.Renderer(client))
    instance: Renderer | None = None

    def source_for(mode: str) -> PageSource:
        nonlocal instance
        if mode != PLAYWRIGHT:
            return fetcher
        if instance is None:
            # 여기까지 와야 브라우저가 뜬다. 목록이 api 면 목록 때문에 뜨는 일은 없다
            instance = build(fetcher)
            logger.info("렌더러를 띄운다 list_mode=%s detail_mode=%s", list_mode, detail_mode)
        return instance

    config = api_config or ApiConfig()
    try:
        list_collector: ListCollector = (
            ApiListCollector(fetcher, config)
            if list_mode == API
            else HtmlListCollector(source_for(list_mode), list_url, selectors.list, list_mode)
        )
        detail_collector: DetailCollector = (
            ApiDetailCollector(fetcher, config)
            if detail_mode == API
            else HtmlDetailCollector(source_for(detail_mode), selectors.detail)
        )
        yield Collectors(
            list_mode=list_mode,
            detail_mode=detail_mode,
            list=list_collector,
            detail=detail_collector,
        )
    finally:
        if instance is not None:
            await instance.aclose()


def html_collectors(
    source: PageSource, list_url: str, selectors: SelectorSet, mode: str = STATIC
) -> Collectors:
    """HTML 한 경로로만 도는 수집기. 브라우저를 여기서 띄우지 않는다.

    이미 열려 있는 `PageSource` 를 그대로 쓰는 자리가 있다 — 렌더러를 밖에서 열어 둔 호출과,
    가짜 소스를 끼우는 시험이다. 어느 쪽이든 수명은 부르는 쪽이 들고 있다.
    """
    return Collectors(
        list_mode=mode,
        detail_mode=mode,
        list=HtmlListCollector(source, list_url, selectors.list, mode),
        detail=HtmlDetailCollector(source, selectors.detail),
    )


def _id_from_link(link: str) -> str:
    """상세 링크의 마지막 경로 조각. 목록이 HTML 이고 상세가 API 인 사이트가 쓴다.

    id 를 쿼리 문자열에 두는 사이트는 여기서 다루지 않는다. 그런 사이트가 나오면 무엇을
    id 로 볼지 설정에 적게 하는 것이 맞고, 지금 추측으로 고르면 조용히 틀린 공고를 가져온다.
    """
    path = urlsplit(link).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else ""
