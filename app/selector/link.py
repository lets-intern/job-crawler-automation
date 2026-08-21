"""목록 항목에서 상세 URL 을 뽑는다. 뽑히지 않으면 왜 안 되는지를 같이 돌려준다.

파서와 생성 시점 자체 검증이 같은 판정을 쓰기 위한 모듈이다. 두 곳이 각자 판정하면
"검증은 통과했는데 실행은 실패한다"가 생긴다 — 실제로 그렇게 됐다. 한화에서 모델이
`list.link` 로 `h4.recruit-title` 을 골랐고, 검증이 노드 수만 세어 20/20 으로 통과시켰다.

그래서 `list.link` 의 성공 기준은 **노드를 잡았는가**가 아니라 **따라갈 수 있는 URL 이
나오는가**다. `href` 가 없는 요소를 잡았거나 `javascript:`, `#` 뿐이면 노드가 스무 개여도
실패다.

절대 URL 로 만드는 것은 여기서 하지 않는다. 상대경로는 그대로 돌려주고, 목록 URL 과 합치는
것은 파서의 몫이다. 조립된 절대 URL 이든 상대경로든 마지막에는 공용 fetch 클라이언트가 다시
http(s) 인지 본다 (`.claude/rules/crawling.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4.element import Tag

from app.selector.schema import ListSelectors

# 크롤러가 따라갈 수 있는 스킴. 이 밖은 링크가 아니라 페이지 안에서 도는 동작이다.
FOLLOWABLE_SCHEMES: tuple[str, ...] = ("http", "https")


@dataclass(frozen=True)
class LinkResult:
    """항목 하나의 상세 링크. `reason` 이 비어 있을 때만 `url` 이 값이다."""

    url: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.reason


def resolve_link(node: Tag, selectors: ListSelectors) -> LinkResult:
    """항목 노드 하나에서 상세 URL 을 뽑는다.

    셀렉터 문법 오류는 `SelectorSyntaxError` 로 그대로 올라간다. 호출부가 그 실패를 필드
    문법 오류로 따로 적기 때문에 여기서 사유 문자열로 바꾸지 않는다.
    """
    if not selectors.link:
        return LinkResult(reason="list.link 셀렉터가 비어 있다. 목록에 상세 링크가 없다는 응답이다")

    found = node.select(selectors.link)
    if not found:
        return LinkResult(reason="list.link 셀렉터가 항목 안에서 노드를 찾지 못했다")

    href = found[0].get("href")
    if not isinstance(href, str) or not href.strip():
        return LinkResult(
            reason=f"`{selectors.link}` 이 잡은 <{found[0].name}> 에 href 가 없다. "
            "a 태그가 아닌 요소를 골랐을 수 있다"
        )

    href = href.strip()
    if not followable(href):
        return LinkResult(reason=f"따라갈 수 있는 링크가 아니다: {href}")
    return LinkResult(url=href)


def followable(url: str) -> bool:
    """크롤러가 따라갈 수 있는 URL 인가.

    스킴이 없으면 상대경로이고, 목록 URL 과 합치면 http(s) 가 되므로 통과시킨다.
    `#` 로 시작하는 것은 같은 페이지 안의 앵커라 상세로 가지 않는다.
    """
    value = url.strip()
    if not value or value.startswith("#"):
        return False
    scheme = urlsplit(value).scheme
    return not scheme or scheme in FOLLOWABLE_SCHEMES
