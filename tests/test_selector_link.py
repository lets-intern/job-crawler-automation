"""`list.link` 판정 테스트.

픽스처 셋을 쓴다. 셋 다 네트워크에 나가지 않는다.

- `hanwha-list-items-20260822.html`: 2026-08-22 에 렌더한 한화 목록에서 항목 3개만 남긴 것.
  항목 안에 `a` 가 하나도 없다
- `hyundai-list-items-20260822.html`: 같은 날 렌더한 현대자동차 목록에서 항목 3개만 남긴 것.
  `a` 는 있지만 `href` 가 전부 `javascript:` 다
- `pythonorg-jobs-list-20260821.html`: 정상 `href` 가 있는 목록

노드 수만 세던 때는 앞의 둘도 통과했다. 그것이 이 파일이 막는 것이다.
"""

from __future__ import annotations

import pathlib

from bs4 import BeautifulSoup

from app.selector.link import followable, resolve_link
from app.selector.schema import ListSelectors, validate_selectors
from app.selector.verify import verify_selectors

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
HANWHA_HTML = (FIXTURES / "hanwha-list-items-20260822.html").read_text(encoding="utf-8")
HYUNDAI_HTML = (FIXTURES / "hyundai-list-items-20260822.html").read_text(encoding="utf-8")
PYTHONORG_HTML = (FIXTURES / "pythonorg-jobs-list-20260821.html").read_text(encoding="utf-8")

# 생성 모델이 실제로 골랐던 셀렉터. `h4.recruit-title` 은 링크가 아니다
HANWHA_LIST = ListSelectors(
    item=".recruit-list > li",
    title=".recruit-title",
    link=".recruit-title",
    date=".recruit-terms .terms",
    company=".affiliate-name",
)

HYUNDAI_LIST = ListSelectors(
    item="#applyList .apply__list > li",
    title=".top strong",
    link="a",
    date=".d__day",
)

PYTHONORG_LIST = ListSelectors(
    item="ol.list-recent-jobs > li",
    title="span.listing-company-name > a",
    link="span.listing-company-name > a",
    date="span.listing-posted time",
)

DETAIL = {
    "title": "h1",
    "body": "div",
    "requirements": "",
    "deadline": "",
    "department": "",
}


def items(html: str, selectors: ListSelectors) -> list:
    return BeautifulSoup(html, "html.parser").select(selectors.item)


def report_for(html: str, selectors: ListSelectors) -> dict:
    """목록 셀렉터만 픽스처에 돌린다. 상세 판정은 이 테스트의 관심이 아니다."""
    full = validate_selectors({"list": selectors.model_dump(), "detail": DETAIL})
    result = verify_selectors(full, html, "<html><h1>t</h1><div>b</div></html>")
    return {field.name: field for field in result.fields}


def test_an_element_without_an_anchor_fails_even_with_every_node_matched() -> None:
    """한화: 항목 3건을 다 잡지만 링크는 0건이다."""
    nodes = items(HANWHA_HTML, HANWHA_LIST)
    assert len(nodes) == 3
    assert all(not node.select("a") for node in nodes)

    fields = report_for(HANWHA_HTML, HANWHA_LIST)
    assert fields["list.item"].matches == 3
    assert fields["list.title"].matches == 3
    assert fields["list.link"].matches == 0
    assert fields["list.link"].status == "failed"
    assert "href 가 없다" in fields["list.link"].message


def test_a_javascript_href_fails() -> None:
    """현대자동차: `a` 는 잡히지만 `href` 가 `javascript:` 라 따라갈 수 없다."""
    nodes = items(HYUNDAI_HTML, HYUNDAI_LIST)
    assert len(nodes) == 3
    assert all(node.select("a") for node in nodes)

    fields = report_for(HYUNDAI_HTML, HYUNDAI_LIST)
    assert fields["list.item"].matches == 3
    assert fields["list.link"].matches == 0
    assert fields["list.link"].status == "failed"
    assert "javascript:" in fields["list.link"].message


def test_a_real_href_is_a_success() -> None:
    fields = report_for(PYTHONORG_HTML, PYTHONORG_LIST)
    assert fields["list.link"].status == "ok"
    assert fields["list.link"].matches == fields["list.item"].matches


def test_the_failed_field_is_named_in_the_report() -> None:
    full = validate_selectors({"list": HANWHA_LIST.model_dump(), "detail": DETAIL})
    result = verify_selectors(full, HANWHA_HTML, "<html><h1>t</h1><div>b</div></html>")

    assert "list.link" in result.failed
    assert result.ok is False
    # 목록 전체가 실패한 것은 아니다. 링크만 못 뽑는 것이지 목록은 읽힌다
    assert result.list_missing is False


def test_resolve_link_says_why_it_failed() -> None:
    hanwha = resolve_link(items(HANWHA_HTML, HANWHA_LIST)[0], HANWHA_LIST)
    assert hanwha.ok is False
    assert hanwha.url == ""
    assert "href 가 없다" in hanwha.reason

    hyundai = resolve_link(items(HYUNDAI_HTML, HYUNDAI_LIST)[0], HYUNDAI_LIST)
    assert hyundai.ok is False
    assert "javascript:" in hyundai.reason

    ok = resolve_link(items(PYTHONORG_HTML, PYTHONORG_LIST)[0], PYTHONORG_LIST)
    assert ok.ok is True
    assert ok.url.startswith("/jobs/")


def test_only_http_and_a_relative_path_are_followable() -> None:
    assert followable("https://talent.hyundai.com/apply/applyView.hc?recuYy=2026") is True
    assert followable("/jobs/8126/") is True
    assert followable("javascript:void(0)") is False
    assert followable("javascript:;") is False
    assert followable("#") is False
    assert followable("mailto:recruit@example.com") is False
    assert followable("") is False
