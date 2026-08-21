"""정적으로 받은 HTML 이 껍데기인지 본다.

셀렉터가 0개 매칭일 때 원인은 둘 중 하나다. 사이트가 마크업을 바꿨거나, 목록을 JS 가 그려서
정적 HTML 에는 애초에 없거나. 둘은 조치가 다르다 — 앞은 셀렉터 재작성이고 뒤는 렌더 모드
승격이다. 실패 사유에 어느 쪽인지가 없으면 운영자는 매번 페이지를 직접 열어 봐야 한다.

판정은 `seeds/sample-sites.json` 의 실측을 기준으로 한다. 같은 방법(script·style·nav·header·
footer 제거 후 본문 길이와 반복 항목 수)으로 잰 값이다.

| 사이트 | 본문 | 반복 항목 | 실제 |
|---|---|---|---|
| 롯데 | 5,685자 | 6 | 정적으로 목록 있음 |
| 삼성 | 816자 | 4 | 정적으로 목록 있음 |
| SK | 608자 | 0 | JS 렌더 |
| 한화 | 70자 | 0 | JS 렌더 |
| LG | 10자 | 0 | JS 렌더 |
| 현대자동차 | 13자 | 0 | JS 렌더 |

목록이 있는 쪽의 최소가 816자·4항목, 없는 쪽의 최대가 608자·0항목이다. 경계는 그 사이에 둔다.

**여기서 렌더 모드를 바꾸지 않는다.** 승격은 운영자가 정한다 (`.claude/rules/crawling.md`).
이 모듈이 하는 것은 사유 한 줄을 더 적는 것뿐이다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from bs4 import BeautifulSoup
from bs4.element import Tag

# 본문에서 걷어내는 것. 어느 페이지에나 있고 목록이 있는지와 무관하다
_IGNORED = ("script", "style", "noscript", "svg", "nav", "header", "footer")

# 목록이 있는 페이지는 이보다 훨씬 길다. 실측에서 목록 있는 쪽의 최소가 816자다
SHELL_TEXT_LIMIT = 700

# 같은 모양의 형제가 이만큼 있어야 목록으로 본다. 실측에서 목록 있는 쪽의 최소가 4다
LIST_MIN_REPEATS = 3

PROMOTION_NOTICE = "정적으로 목록을 찾지 못했다. 렌더 모드로 올려 다시 시도할 수 있다"


@dataclass(frozen=True)
class ShellVerdict:
    """무엇을 보고 그렇게 판정했는지를 숫자로 들고 있다."""

    text_chars: int
    repeating_items: int

    @property
    def is_shell(self) -> bool:
        return self.repeating_items < LIST_MIN_REPEATS and self.text_chars < SHELL_TEXT_LIMIT

    def describe(self) -> str:
        return f"본문 {self.text_chars}자, 반복 항목 {self.repeating_items}개"


def inspect_static_html(html: str) -> ShellVerdict:
    """본문 길이와 반복 항목 수를 센다. `seeds/sample-sites.json` 과 같은 방법이다."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(_IGNORED):
        node.decompose()

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return ShellVerdict(text_chars=len(text), repeating_items=_max_repeats(soup))


def promotion_hint(html: str, render_mode: str) -> str | None:
    """껍데기면 승격 안내를, 아니면 None 을 돌려준다.

    이미 렌더로 도는 크롤러에는 안내하지 않는다. 그 경우 0개 매칭은 셀렉터 문제이지
    가져오는 방식의 문제가 아니다.
    """
    if render_mode != "static":
        return None

    verdict = inspect_static_html(html)
    if not verdict.is_shell:
        return None
    return f"{PROMOTION_NOTICE} ({verdict.describe()})"


def _max_repeats(soup: BeautifulSoup) -> int:
    """같은 부모 아래에서 태그와 class 가 같은 형제가 가장 많은 곳의 개수.

    목록은 어떤 사이트에서도 같은 모양의 형제가 여러 개 있는 모양이다. 그 최대치가 몇
    개인지만 보면 되고, 어느 셀렉터가 잡는지는 여기서 알 필요가 없다.

    혼자 있는 요소는 반복이 아니라 0으로 센다. 어느 페이지에나 요소는 하나쯤 있어서, 그것을
    1로 세면 빈 페이지와 항목 하나짜리 목록이 같은 값이 된다.
    """
    best = 0
    for parent in soup.find_all(True):
        signatures = Counter(
            (child.name, tuple(_classes(child)))
            for child in parent.find_all(recursive=False)
            if isinstance(child, Tag)
        )
        if signatures:
            best = max(best, signatures.most_common(1)[0][1])
    return best if best > 1 else 0


def _classes(node: Tag) -> list[str]:
    value = node.get("class")
    if isinstance(value, str):
        return [value]
    return sorted(value or [])
