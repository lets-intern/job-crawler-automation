"""본문 추출이 블록 구조를 지키는지.

`get_text()` 를 그냥 부르면 `<h3>조직소개</h3>` 와 뒤따르는 `<p>` 가 한 줄로 이어붙는다.
2026-08-22 에 수집한 현대자동차 공고 본문 1,955자가 그렇게 한 문단으로 들어왔다.

정규화로는 고칠 수 없다. 정규화가 값을 받을 때는 어디가 문단 경계였는지 이미 사라진 뒤다.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.crawler.parser import field_text

SECTIONS = """
<div class="body">
  <h3>조직소개</h3><p>우리 조직은 차량보안을 총괄한다.</p>
  <h3>직무상세</h3><p>사고를 모니터링한다.</p>
</div>
"""

INLINE = (
    '<div class="body"><p>본문 안의 <strong>강조</strong>와 '
    '<a href="#">링크</a>는 이어진다.</p></div>'
)

BULLETS = '<div class="req"><ul><li>학사 이상</li><li>3년 이상 경력</li></ul></div>'


def _lines(html: str, selector: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = field_text(soup, selector, "detail.body")
    return [line.strip() for line in text.split("\n") if line.strip()]


def test_block_boundaries_become_line_breaks() -> None:
    assert _lines(SECTIONS, ".body") == [
        "조직소개",
        "우리 조직은 차량보안을 총괄한다.",
        "직무상세",
        "사고를 모니터링한다.",
    ]


def test_inline_tags_stay_on_one_line() -> None:
    """인라인까지 줄을 넣으면 문장 하나가 여러 줄로 쪼개진다."""
    assert _lines(INLINE, ".body") == ["본문 안의 강조와 링크는 이어진다."]


def test_list_items_become_separate_lines() -> None:
    """자격요건이 한 줄로 붙어 오던 것도 같은 원인이었다."""
    assert _lines(BULLETS, ".req") == ["학사 이상", "3년 이상 경력"]


def test_extraction_does_not_mutate_the_tree() -> None:
    """같은 트리에서 다른 필드도 뽑는다. 트리를 바꾸면 뒤 추출이 달라진다."""
    soup = BeautifulSoup(SECTIONS, "html.parser")
    before = str(soup)

    field_text(soup, ".body", "detail.body")

    assert str(soup) == before
