"""상세 페이지가 없는 사이트도 등록되고 실행된다.

삼성처럼 상세를 JS 로 그려 별도 주소가 없는 사이트가 있다. `list.link` 를 필수로 두면
그런 사이트는 등록 자체가 안 되고 워크플로우까지 갈 수 없다.

셀렉터가 비어 있는 것과, 셀렉터가 있는데 0개 매칭인 것은 다르다. 앞은 없는 것이고 뒤는
실패다 — 화면의 `건너뜀` / `실패` 구분과 같은 기준이다.
"""

from __future__ import annotations

import pytest

from app.crawler.parser import FieldParseError, list_only, parse_list
from app.selector.schema import ListSelectors

LIST_HTML = """
<ul class="jobs">
  <li><h3>백엔드 개발자</h3><span class="d">2026-09-30</span></li>
  <li><h3>프론트엔드 개발자</h3><span class="d">2026-10-15</span></li>
</ul>
"""

WITH_LINK_HTML = """
<ul class="jobs">
  <li><h3><a href="/jobs/1">백엔드 개발자</a></h3><span class="d">2026-09-30</span></li>
</ul>
"""

NO_LINK = ListSelectors(
    item="ul.jobs li", title="h3", link="", date=".d", company="", link_template=""
)
BROKEN_LINK = ListSelectors(
    item="ul.jobs li", title="h3", link="a.detail", date=".d", company="", link_template=""
)


def test_list_only_is_true_when_both_link_fields_are_empty() -> None:
    assert list_only(NO_LINK) is True
    assert list_only(BROKEN_LINK) is False


def test_a_site_without_detail_links_still_yields_items() -> None:
    result = parse_list(LIST_HTML, NO_LINK, "https://example.test/jobs")

    assert [item.title for item in result.items] == ["백엔드 개발자", "프론트엔드 개발자"]
    # 상세로 갈 길이 없으므로 목록 주소가 남는다
    assert {item.link for item in result.items} == {"https://example.test/jobs"}
    assert all(item.detail_absent for item in result.items)
    assert result.failures == []


def test_a_selector_that_matches_nothing_is_still_a_failure() -> None:
    """셀렉터를 적어 뒀는데 못 찾은 것은 여전히 실패다. 이것까지 넘기면 안 된다."""
    with pytest.raises(FieldParseError) as caught:
        parse_list(LIST_HTML, BROKEN_LINK, "https://example.test/jobs")

    assert "link" in str(caught.value)


def test_a_normal_site_is_unaffected() -> None:
    selectors = ListSelectors(
        item="ul.jobs li", title="h3", link="a", date=".d", company="", link_template=""
    )

    result = parse_list(WITH_LINK_HTML, selectors, "https://example.test/jobs")

    assert result.items[0].link == "https://example.test/jobs/1"
    assert result.items[0].detail_absent is False


def test_a_list_only_record_takes_title_and_deadline_from_the_list() -> None:
    """상세를 안 따라가면 title 이 올 곳은 목록뿐이다. 비워 두면 공고를 알아볼 수 없다."""
    from app.crawler.parser import ListItem
    from app.crawler.runner import _record
    from app.selector.schema import DETAIL_FIELDS

    item = ListItem(
        index=0,
        title="백엔드 개발자",
        link="https://example.test/jobs",
        date="2026-09-30",
        company="삼성",
        detail_absent=True,
    )

    record = _record(item, dict.fromkeys(DETAIL_FIELDS, ""))

    assert record["title"] == "백엔드 개발자"
    assert record["deadline"] == "2026-09-30"
    assert record["company"] == "삼성"
    # 상세에서 오는 값은 비어 있는 것이 맞다. 없는 페이지를 지어내지 않는다
    assert record["body"] == ""


def test_a_normal_record_still_prefers_the_detail_page() -> None:
    from app.crawler.parser import ListItem
    from app.crawler.runner import _record

    item = ListItem(index=0, title="목록 제목", link="https://x/1", date="2026-01-01")
    detail = {
        "title": "상세 제목",
        "body": "본문",
        "requirements": "",
        "deadline": "2026-12-31",
        "department": "",
        "company": "",
    }

    record = _record(item, detail)

    assert record["title"] == "상세 제목"
    assert record["deadline"] == "2026-12-31"
