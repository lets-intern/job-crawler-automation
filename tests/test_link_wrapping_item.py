"""링크가 항목을 감싸는 목록. 뤼튼 등록이 여기서 막혔다.

React 로 만든 목록에서 흔한 모양이다.

    <a data-testid="공고_아이템" href="/ko/o/189525">
      <li class="opening-list__OpeningItemContainer-...">   <- 항목으로 잡히는 것
        <span class="...Title...">AX Agent Developer</span>

`node.select()` 는 자손만 뒤진다. 항목이 안쪽 `li` 로 잡히면 링크는 영원히 안 나오고,
28개 항목이 전부 실패해 "쓸 수 있는 항목 0건" 이 된다 — 목록 셀렉터는 멀쩡한데도.

2026-08-27 에 실제로 받은 HTML 을 줄인 것이 `tests/fixtures/wrtn-list-items-20260827.html`
이다. 이 파일이 잠그는 것은 "링크가 항목 밖에 있어도 찾는다" 하나다.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from app.selector.link import resolve_link
from app.selector.schema import ListSelectors

FIXTURE = Path(__file__).parent / "fixtures" / "wrtn-list-items-20260827.html"

WRTN = ListSelectors(
    item="li.opening-list__OpeningItemContainer-sc-ece8b094-2",
    title="span.opening-list__OpeningListItemTitle-sc-ece8b094-3",
    link='a[data-testid="공고_아이템"]',
    date="",
)


def _items() -> list:
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
    return soup.select(WRTN.item)


def test_항목은_원래도_잡혔다() -> None:
    """목록 셀렉터는 처음부터 멀쩡했다. 실패한 것은 링크뿐이다."""
    assert len(_items()) == 2


def test_항목을_감싼_링크를_찾는다() -> None:
    results = [resolve_link(node, WRTN) for node in _items()]

    assert [r.reason for r in results] == ["", ""]
    assert [r.url for r in results] == ["/ko/o/189525", "/ko/o/189526"]


def test_항목마다_자기_링크를_갖는다() -> None:
    """가장 가까운 조상을 잡는다. 목록 전체를 감싼 것을 잡으면 전부 같은 주소가 된다."""
    urls = {resolve_link(node, WRTN).url for node in _items()}
    assert len(urls) == 2


def test_안쪽에_있으면_그것이_먼저다() -> None:
    """감싼 링크가 있어도 항목 안의 링크가 우선이다. 가까운 쪽이 그 항목의 것이다."""
    html = """
    <a href="/바깥"><li class="item"><span><a href="/안쪽">제목</a></span></li></a>
    """
    node = BeautifulSoup(html, "html.parser").select_one("li.item")
    assert node is not None

    result = resolve_link(node, ListSelectors(item="li.item", title="span", link="a", date=""))

    assert result.url == "/안쪽"


def test_너무_멀면_올라가지_않는다() -> None:
    """끝까지 올라가면 머리말의 링크나 목록 전체를 감싼 것을 잡는다."""
    html = """
    <a href="/너무-멀다">
      <div><div><div><div><li class="item"><span>제목</span></li></div></div></div></div>
    </a>
    """
    node = BeautifulSoup(html, "html.parser").select_one("li.item")
    assert node is not None

    result = resolve_link(node, ListSelectors(item="li.item", title="span", link="a", date=""))

    assert not result.ok
    assert "찾지 못했다" in result.reason


def test_href_없는_조상은_사유가_바뀐다() -> None:
    """조상을 찾았는데 href 가 없으면 "못 찾았다" 가 아니라 "href 가 없다" 다."""
    html = '<div class="wrap"><li class="item"><span>제목</span></li></div>'
    node = BeautifulSoup(html, "html.parser").select_one("li.item")
    assert node is not None

    result = resolve_link(
        node, ListSelectors(item="li.item", title="span", link="div.wrap", date="")
    )

    assert not result.ok
    assert "href 가 없다" in result.reason
