"""모델이 필수 필드를 채우지 못했을 때 크롤러를 버리지 않는다.

통째로 거절하면 운영자가 손으로 고칠 대상조차 없다. `.claude/rules/llm.md` 는 손 편집을
첫 번째 수단으로 두므로, 빈 채로 draft 에 남기고 어느 자리가 비었는지 알려야 한다.
"""

from __future__ import annotations

import pytest

from app.selector.schema import (
    SelectorSchemaError,
    parse_selectors,
    parse_selectors_allowing_empty,
)

FULL = """
{"list": {"item": "li.job", "title": "h4", "link": "a", "date": "time"},
 "detail": {"title": "h1", "body": ".body", "requirements": "", "deadline": "", "department": ""}}
"""

MISSING_DATE = """
{"list": {"item": "li.job", "title": "h4", "link": "a", "date": ""},
 "detail": {"title": "h1", "body": ".body", "requirements": "", "deadline": "", "department": ""}}
"""


def test_strict_parse_still_rejects_a_missing_field() -> None:
    """기본 경로는 그대로 엄격하다. 느슨한 판정이 새어 나가면 안 된다."""
    with pytest.raises(SelectorSchemaError) as caught:
        parse_selectors(MISSING_DATE)

    assert caught.value.reason == "missing_field"


def test_lenient_parse_keeps_the_selector_and_names_the_empty_field() -> None:
    selectors, empty = parse_selectors_allowing_empty(MISSING_DATE)

    assert empty == ["list.date"]
    # 비어 있는 자리는 비워 둔다. 무엇이었을지 추측해 채우지 않는다.
    assert selectors.list.date == ""
    # 나머지는 살아 있어야 손으로 고칠 값이 남는다.
    assert selectors.list.item == "li.job"
    assert selectors.list.title == "h4"
    assert selectors.detail.title == "h1"


def test_lenient_parse_reports_nothing_when_the_response_is_complete() -> None:
    selectors, empty = parse_selectors_allowing_empty(FULL)

    assert empty == []
    assert selectors.list.date == "time"


def test_lenient_parse_still_rejects_an_unknown_field() -> None:
    """비어 있는 것은 봐주지만 지어낸 필드는 봐주지 않는다."""
    with pytest.raises(SelectorSchemaError) as caught:
        parse_selectors_allowing_empty(
            '{"list": {"item": "li", "title": "h4", "link": "a", "date": "t", "links": "x"},'
            ' "detail": {"title": "h1", "body": "b", "requirements": "",'
            ' "deadline": "", "department": ""}}'
        )

    assert caught.value.reason == "unknown_field"
