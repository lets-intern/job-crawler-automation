"""등록할 때 상세로 가는 길을 스스로 알아낸다. 운영자는 목록 URL 하나만 넣는다.

순서가 정해져 있고, 앞 단계로 풀리면 뒤 단계는 하지 않는다.

| 순서 | 하는 일 | 다음으로 넘어가는 조건 |
|---|---|---|
| 1 | 목록을 `httpx` 로 받는다 | 항목이 없거나 상세 주소를 만들 값이 없다 |
| 2 | 렌더한다 | 렌더해도 항목에 상세 주소가 없다 |
| 3 | 항목을 클릭하고 그때 나가는 요청을 본다 | 클릭으로 상세에 도달했다 |
| 4 | 알아낸 요청을 `httpx` 로 다시 부른다 | 같은 응답이 오면 채택 |

**정적으로 되면 브라우저를 띄우지 않는다.** 렌더 한 번이 정적 fetch 의 몇십 배를 쓴다
(`.claude/rules/crawling.md`). 그래서 브라우저를 여는 것은 이 함수가 직접 하지 않고, 필요한
순간에 부르는 `open_probe` 로 받는다 — 1번에서 끝나면 그것을 한 번도 부르지 않는다.

## 판정은 제안이다

여기서 나오는 것은 `Discovery` 한 개이고, 어디에도 저장하지 않는다. 무엇을 저장할지는 운영자가
정한다. 여섯 사이트는 사람이 이미 확인해 설정해 뒀고, 그것을 이 판정으로 덮어쓰지 않는다
(`.claude/rules/llm.md` 의 "모델은 제안자이지 권위가 아니다" 와 같은 자리다).

## 근거를 문장으로 남긴다

`evidence` 는 사람이 읽는 한 줄이다. "정적 목록에 항목 0건, 렌더 후 16건, 항목에 상세 주소가
없어 클릭했다" 처럼 세 경로가 각각 다른 문장을 남긴다. 판정만 남기면 다음 사람이 왜 렌더로
정해졌는지 알 수 없어 처음부터 다시 재게 된다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.crawler.click_probe import DETAIL_UNREACHABLE, probe_click
from app.crawler.collect import API
from app.crawler.failures import LIST_EMPTY
from app.crawler.fetcher import FetchError, FetchPolicy
from app.crawler.parser import (
    CrawlDataError,
    ListItem,
    list_only,
    parse_list,
    select_nodes,
)
from app.crawler.playwright import PLAYWRIGHT, STATIC, ObservedRequest, ProbeSession
from app.selector.detail_path import (
    DetailPath,
    IdSource,
    confirm_api_path,
    confirm_document_path,
    document_path,
    id_candidates,
    pick_detail_request,
    propose_detail_config,
)
from app.selector.schema import SelectorSet

# 브라우저를 여는 쪽. 필요할 때만 불린다 (`Renderer.open_probe`)
ProbeOpener = Callable[[str], AbstractAsyncContextManager[ProbeSession]]


@dataclass(frozen=True)
class Discovery:
    """등록할 때의 판정 하나. 저장은 운영자가 한다.

    `ok` 가 거짓이면 `failure` 가 `list_empty` 이거나 `detail_unreachable` 이고, 무엇을 보고
    그렇게 판정했는지는 `evidence` 와 `reason` 에 나뉘어 있다.
    """

    list_mode: str = STATIC
    detail_mode: str = ""
    detail: DetailPath | None = None
    evidence: str = ""
    reason: str = ""
    failure: str = ""
    list_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.reason and not self.failure


async def discover_detail_path(
    list_url: str,
    selectors: SelectorSet,
    *,
    fetcher: FetchPolicy,
    open_probe: ProbeOpener | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> Discovery:
    """목록 URL 하나로 상세로 가는 길을 찾는다. 찾은 것은 제안으로 돌려준다.

    `sleep` 은 클릭 뒤 기다리는 자리다. 시험이 실제로 3초를 기다리지 않게 바꿔 끼운다
    (`app/crawler/fetcher.py` 의 `clock`·`sleep` 과 같은 자리).
    """
    static_items, static_note = await _items_from_static(fetcher, list_url, selectors)
    static_count = len(static_items)

    if static_items and not _needs_more(static_items, selectors):
        return Discovery(
            list_mode=STATIC,
            detail_mode=STATIC,
            detail=document_path(static_items[0].link, "목록 항목의 링크를 그대로 따라간다"),
            evidence=(
                f"정적 목록에서 항목 {static_count}건과 상세 주소를 찾았다. "
                "브라우저를 띄우지 않았다"
            ),
            list_count=static_count,
        )

    if open_probe is None:
        return Discovery(
            list_mode=STATIC,
            evidence=f"정적 목록 판정: {static_note}",
            failure=LIST_EMPTY if not static_items else DETAIL_UNREACHABLE,
            reason=(
                "정적으로는 상세로 갈 길이 없는데 브라우저를 열 수 없다. "
                "렌더가 가능한 배포에서 다시 등록한다"
            ),
            list_count=static_count,
        )

    async with open_probe(list_url) as session:
        return await _discover_with_browser(
            session,
            fetcher=fetcher,
            selectors=selectors,
            static_count=static_count,
            sleep=sleep,
        )


async def _discover_with_browser(
    session: ProbeSession,
    *,
    fetcher: FetchPolicy,
    selectors: SelectorSet,
    static_count: int,
    sleep: Callable[[float], Awaitable[None]] | None,
) -> Discovery:
    """렌더한 목록으로 2~4번을 돈다. 브라우저는 부르는 쪽이 닫는다."""
    prefix = f"정적 목록에 항목 {static_count}건"
    rendered, rendered_note = _items_from_html(session.html, session.url, selectors)
    count = len(rendered)

    if not rendered:
        return Discovery(
            list_mode=PLAYWRIGHT,
            evidence=f"{prefix}, 렌더 후에도 0건",
            failure=LIST_EMPTY,
            reason=f"렌더한 목록에서도 항목을 잡지 못했다: {rendered_note}",
            list_count=0,
        )

    if not _needs_more(rendered, selectors):
        item = rendered[0]
        confirmation = await confirm_document_path(fetcher, item.link, item.title)
        detail_mode = STATIC if confirmation.adopted else PLAYWRIGHT
        tail = (
            "상세 문서는 정적으로도 열렸다"
            if confirmation.adopted
            else f"상세 문서는 정적으로 열리지 않았다 — {confirmation.reason}"
        )
        return Discovery(
            list_mode=PLAYWRIGHT,
            detail_mode=detail_mode,
            detail=document_path(item.link, tail),
            evidence=(
                f"{prefix}, 렌더 후 {count}건. 항목에서 상세 주소를 얻어 클릭하지 않았다. {tail}"
            ),
            list_count=count,
        )

    outcome = await probe_click(
        session.page,
        context=session.context,
        log=session.log,
        item_selector=selectors.list.item,
        sleep=sleep,
    )
    if not outcome.reached:
        return Discovery(
            list_mode=PLAYWRIGHT,
            evidence=f"{prefix}, 렌더 후 {count}건, 항목에 상세 주소가 없어 클릭했다",
            failure=outcome.failure or DETAIL_UNREACHABLE,
            reason=outcome.reason,
            list_count=count,
        )

    signals = ", ".join(outcome.signals)
    clicked = (
        f"{prefix}, 렌더 후 {count}건, 항목에 상세 주소가 없어 클릭했다. "
        f"{outcome.target} 를 눌러 {signals}"
    )
    node = _first_node(session.html, selectors)
    candidates = id_candidates(node) if node is not None else []
    picked = pick_detail_request(outcome.requests, candidates) if candidates else None

    if picked is not None:
        return await _from_api_request(fetcher, picked, clicked=clicked, count=count)

    if outcome.url and outcome.url != session.url:
        # 클릭이 상세 문서로 데려갔다. 주소가 있으니 API 를 찾을 필요가 없다
        confirmation = await confirm_document_path(fetcher, outcome.url, _title(rendered))
        detail_mode = STATIC if confirmation.adopted else PLAYWRIGHT
        tail = (
            "그 주소는 정적으로도 열렸다"
            if confirmation.adopted
            else f"그 주소는 정적으로 열리지 않았다 — {confirmation.reason}"
        )
        return Discovery(
            list_mode=PLAYWRIGHT,
            detail_mode=detail_mode,
            detail=document_path(outcome.url, tail),
            evidence=f"{clicked} — 상세 문서 주소를 알아냈다. {tail}",
            list_count=count,
        )

    return Discovery(
        list_mode=PLAYWRIGHT,
        evidence=clicked,
        failure=DETAIL_UNREACHABLE,
        reason=(
            f"클릭 뒤 나간 요청 {len(outcome.requests)}건 중 이 공고를 지목한 것이 없고 "
            "주소도 그대로다. 상세 경로를 손으로 적는다"
        ),
        list_count=count,
    )


async def _from_api_request(
    fetcher: FetchPolicy,
    picked: tuple[ObservedRequest, IdSource],
    *,
    clicked: str,
    count: int,
) -> Discovery:
    """클릭이 알려 준 요청을 설정으로 만들고 `httpx` 로 다시 불러 확인한다."""
    request, source = picked
    path = propose_detail_config(request, source)
    if not path.ok:
        return Discovery(
            list_mode=PLAYWRIGHT,
            evidence=f"{clicked} — 요청 {request.url} 을 찾았다",
            failure=DETAIL_UNREACHABLE,
            reason=path.reason,
            list_count=count,
        )

    confirmation = await confirm_api_path(fetcher, path, request)
    if not confirmation.adopted:
        # 브라우저에서만 되는 요청은 채택하지 않는다. 저장하면 이후 실행이 전부 실패한다
        return Discovery(
            list_mode=PLAYWRIGHT,
            evidence=f"{clicked} — 상세 요청 {request.url} 을 알아냈다",
            failure=DETAIL_UNREACHABLE,
            reason=f"알아낸 요청을 다시 불러 확인하지 못했다: {confirmation.reason}",
            list_count=count,
        )

    return Discovery(
        list_mode=PLAYWRIGHT,
        detail_mode=API,
        detail=path,
        evidence=(
            f"{clicked} — 상세 API 를 알려 줬고, 같은 요청을 httpx 로 다시 불러 "
            f"제목과 본문 {confirmation.body_length}자가 같았다"
        ),
        list_count=count,
    )


async def _items_from_static(
    fetcher: FetchPolicy, list_url: str, selectors: SelectorSet
) -> tuple[list[ListItem], str]:
    """1번. 정적으로 받아 항목을 잡아 본다. 실패도 사유 문장으로 돌려준다."""
    try:
        page = await fetcher.fetch(list_url)
    except FetchError as exc:
        return [], f"정적 fetch 가 실패했다: {exc}"
    return _items_from_html(page.text, page.url, selectors)


def _items_from_html(
    html: str, base_url: str, selectors: SelectorSet
) -> tuple[list[ListItem], str]:
    try:
        result = parse_list(html, selectors.list, base_url)
    except CrawlDataError as exc:
        return [], str(exc)
    return result.items, f"항목 {len(result.items)}건"


def _needs_more(items: list[ListItem], selectors: SelectorSet) -> bool:
    """상세로 갈 값이 항목에 없는가. 없으면 렌더나 클릭으로 넘어간다."""
    if list_only(selectors.list):
        return True
    return items[0].detail_absent or not items[0].link.strip()


def _first_node(html: str, selectors: SelectorSet) -> Tag | None:
    """공고 번호를 찾을 항목 노드 하나. 클릭한 것과 같은 첫 항목이다."""
    soup = BeautifulSoup(html, "html.parser")
    nodes = select_nodes(soup, selectors.list.item, "list.item")
    return nodes[0] if nodes else None


def _title(items: list[ListItem]) -> str:
    return items[0].title if items else ""
