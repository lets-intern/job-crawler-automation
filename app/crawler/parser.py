"""셀렉터 JSON 을 HTML 에 적용해 목록 항목과 상세 필드를 뽑는다.

여기서 하는 것은 "셀렉터가 잡은 노드에서 값을 꺼내는 것"까지다. 꺼낸 텍스트는 손대지 않는다 —
앞뒤 공백, 줄바꿈, 사이에 낀 광고 문구를 여기서 지우면 지저분한 값 하나 때문에 셀렉터가
사이트 구조가 아니라 그 사이트의 텍스트에 묶인다. 정제는 정규화 규칙의 몫이다 (`CLAUDE.md`).

이 모듈은 네트워크를 모른다. HTML 문자열을 받아서 결과나 예외를 돌려줄 뿐이고, 가져오는 일은
`app/crawler/fetcher.py` 가 한다.

실패는 두 가지로 나뉘고, 조치가 다르다 (`.claude/rules/crawling.md`).

| 예외 | 뜻 | 조치 |
|---|---|---|
| `SelectorMissError` | 가져오기는 됐는데 item 셀렉터가 0개 매칭 | 재시도 금지. 셀렉터 재작성 |
| `FieldParseError` | 매칭은 됐는데 필요한 필드를 못 읽음 | 그 필드만 보정 |

목록 항목 0건은 실패다. 신규 0건인 정상 실행과 같은 결과로 남기지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from soupsieve import SelectorSyntaxError

from app.selector.schema import DETAIL_FIELDS, DetailSelectors, ListSelectors

# 이 값이 없으면 공고를 식별할 수도, 상세로 따라갈 수도 없다. 나머지는 비어도 항목이 남는다.
REQUIRED_LIST_FIELDS: tuple[str, ...] = ("title", "link")

# 상세에서 이 둘이 비면 적재할 내용이 없다. 나머지는 사이트에 항목 자체가 없을 수 있다.
REQUIRED_DETAIL_FIELDS: tuple[str, ...] = ("title", "body")


class CrawlDataError(Exception):
    """가져오기는 성공한 뒤에 생긴 실패. `error_class` 는 `crawl_runs.error_class` 로 간다."""

    error_class = "parse"


class SelectorMissError(CrawlDataError):
    """item 셀렉터가 0개 매칭. 사이트 구조가 바뀌었거나 JS 렌더링이다."""

    error_class = "selector_miss"


class FieldParseError(CrawlDataError):
    """노드는 잡았는데 필드를 읽지 못했다."""

    error_class = "parse"


@dataclass(frozen=True)
class FieldFailure:
    """항목 하나에서 실패한 필드 하나. `index` 는 목록에서의 순번이다."""

    index: int
    field: str
    message: str


@dataclass(frozen=True)
class ListItem:
    """목록에서 뽑은 항목 하나. `link` 만 절대 URL 로 만들고 나머지는 원문 그대로다."""

    index: int
    title: str
    link: str
    date: str
    # 셀렉터가 없거나 못 찾으면 빈 문자열이다. 회사명이 없는 사이트가 흔하다
    company: str = ""


@dataclass(frozen=True)
class ListParseResult:
    matched: int
    items: list[ListItem]
    failures: list[FieldFailure]


@dataclass(frozen=True)
class DetailParseResult:
    """`fields` 는 상세 셀렉터 이름 그대로다. `missing` 은 셀렉터는 있는데 0개 매칭인 선택 필드."""

    fields: dict[str, str]
    missing: list[str]


def parse_list(html: str, selectors: ListSelectors, base_url: str) -> ListParseResult:
    """목록 페이지에서 항목을 뽑는다. 0개 매칭은 `SelectorMissError` 다."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = _select(soup, selectors.item, "list.item")
    if not nodes:
        raise SelectorMissError(
            f"list.item `{selectors.item}` 이 0개 매칭됐다. 사이트 구조가 바뀌었거나 JS 렌더링이다"
        )

    items: list[ListItem] = []
    failures: list[FieldFailure] = []

    for index, node in enumerate(nodes):
        title = _text(node, selectors.title, f"list.title[{index}]")
        link = _href(node, selectors.link, index)
        date = _text(node, selectors.date, f"list.date[{index}]")
        company = (
            _text(node, selectors.company, f"list.company[{index}]") if selectors.company else ""
        )

        found = {"title": title, "link": link}
        missing = [name for name in REQUIRED_LIST_FIELDS if not found[name]]
        if missing:
            failures.extend(
                FieldFailure(
                    index=index, field=name, message="셀렉터가 항목 안에서 값을 찾지 못했다"
                )
                for name in missing
            )
            continue

        items.append(
            ListItem(
                index=index,
                title=title,
                link=urljoin(base_url, link),
                date=date,
                company=company,
            )
        )

    if not items:
        # 실제로 못 읽은 필드만 적는다. 필수 필드 이름을 통째로 적으면 title 은 멀쩡한데
        # link 만 없는 사이트에서 운영자가 두 필드를 다 뒤지게 된다
        unread = [name for name in REQUIRED_LIST_FIELDS if any(f.field == name for f in failures)]
        raise FieldParseError(
            f"item {len(nodes)}건을 잡았지만 어느 항목에서도 {', '.join(unread)} 를 읽지 못했다"
        )

    return ListParseResult(matched=len(nodes), items=items, failures=failures)


def parse_detail(html: str, selectors: DetailSelectors) -> DetailParseResult:
    """상세 페이지에서 필드를 뽑는다. 필수 필드를 못 읽으면 `FieldParseError` 다."""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    missing: list[str] = []

    for name in DETAIL_FIELDS:
        selector = getattr(selectors, name)
        if not selector:
            # 사이트에 그 항목이 없다는 응답이다. 빈 값이지 실패가 아니다.
            fields[name] = ""
            continue

        value = _text(soup, selector, f"detail.{name}")
        fields[name] = value
        if not value:
            missing.append(name)

    unreadable = [name for name in REQUIRED_DETAIL_FIELDS if not fields[name]]
    if unreadable:
        raise FieldParseError(f"상세에서 필수 필드를 읽지 못했다: {', '.join(unreadable)}")

    return DetailParseResult(fields=fields, missing=missing)


def _select(scope: BeautifulSoup | Tag, selector: str, name: str) -> list[Tag]:
    try:
        return list(scope.select(selector))
    except SelectorSyntaxError as exc:
        raise FieldParseError(f"{name} 셀렉터 문법 오류: {exc}") from exc


def _text(scope: BeautifulSoup | Tag, selector: str, name: str) -> str:
    """첫 매칭 노드의 텍스트를 그대로 돌려준다. 매칭이 없으면 빈 문자열이다."""
    nodes = _select(scope, selector, name)
    if not nodes:
        return ""
    return nodes[0].get_text()


def _href(node: Tag, selector: str, index: int) -> str:
    """상세 링크. `href` 가 없는 노드를 잡았으면 값이 없는 것으로 본다."""
    nodes = _select(node, selector, f"list.link[{index}]")
    if not nodes:
        return ""
    href = nodes[0].get("href")
    if not isinstance(href, str):
        return ""
    return href
