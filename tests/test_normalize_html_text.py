"""`html_text` 규칙 테스트.

LG 상세 API 가 본문과 자격요건을 HTML 조각으로 준다. 수집은 그것을 그대로 `raw_jobs` 에
남기고 (`.claude/rules/data-safety.md`), 소비 측이 읽는 평문으로 펴는 것은 이 규칙이다.

네트워크를 타지 않는다. 실제 값은 `tests/fixtures/lg-detail-api-20260824.json` 에 저장된
LG 응답 한 건이고, 그 안의 `detailContext`·`requiredItem` 이 소비 측에 태그째 나갔던 값이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.normalize.engine import _apply, flatten_html
from app.normalize.rules import build_rule

FIXTURE = Path(__file__).parent / "fixtures" / "lg-detail-api-20260824.json"


@pytest.fixture(scope="module")
def lg_detail() -> dict[str, Any]:
    """LG 상세 응답의 `recList[0]`. HTML 조각이 들어 있는 자리다."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    record = payload["data"]["jobNoticesDetail"]["recList"][0]
    assert isinstance(record, dict)
    return record


def test_block_tags_become_line_breaks() -> None:
    """문단이 붙지 않는다. 태그만 지우면 `가나` 가 된다."""
    assert flatten_html("<p>가</p><p>나</p>") == "가\n나"
    assert flatten_html("가<br>나") == "가\n나"
    assert flatten_html("<ul><li>가</li><li>나</li></ul>") == "가\n나"


def test_inline_tags_do_not_break_the_line() -> None:
    """`span`, `strong` 은 앞뒤 글자와 이어져야 한다. 여기서 줄을 넣으면 문장이 쪼개진다."""
    assert flatten_html("<p><span>보안</span><strong>거버넌스</strong>팀</p>") == "보안거버넌스팀"


def test_entities_come_back_as_characters() -> None:
    """`&amp;` 는 `&` 로, `&nbsp;` 는 공백으로 돌아온다."""
    assert flatten_html("<p>주요 R&amp;R</p>") == "주요 R&R"
    assert flatten_html("<p>가&nbsp;나</p>") == "가 나"
    assert flatten_html("<p>&lt;주의&gt;</p>") == "<주의>"


def test_blank_paragraph_does_not_survive() -> None:
    """`<p>&nbsp;</p>` 는 빈 줄로 뭉개지고 남지 않는다. LG 값 끝에 늘 붙어 온다."""
    assert flatten_html("<p>&nbsp;</p>") == ""
    assert flatten_html("<p>가</p><p>&nbsp;</p><p>나</p>") == "가\n나"
    assert flatten_html("<p>가</p><p><br>&nbsp;</p>") == "가"


def test_consecutive_blank_lines_collapse_to_one() -> None:
    """원문 텍스트에 있던 빈 줄은 남되 셋 이상은 하나로 줄인다."""
    assert flatten_html("<p>가\n\n\n\n나</p>") == "가\n\n나"


def test_attributes_and_comments_leave_nothing_behind() -> None:
    """스타일 속성과 `<!--StartFragment-->` 는 값에 남지 않는다."""
    fragment = '<!--StartFragment--><p style="font-size:10pt;">가</p>'
    assert flatten_html(fragment) == "가"


def test_plain_text_passes_through_unchanged() -> None:
    """규칙이 걸린 필드에 평문이 오는 것은 정상이다. 손대지 않는다."""
    for value in (
        "경력 3년 이상",
        "가\n나",
        "연구개발 R&D 부문",
        "지원 자격: 학사 이상 (전공 무관)",
        "  앞뒤 공백까지 그대로  ",
    ):
        assert flatten_html(value) == value


def test_empty_value_stays_empty() -> None:
    assert flatten_html("") == ""


def test_rule_type_is_wired_into_the_engine() -> None:
    """`_apply` 가 `html_text` 를 처리한다. 설정은 빈 객체다."""
    rule = build_rule("body", "html_text", {})
    assert _apply("<p>가</p><p>나</p>", rule) == "가\n나"


def test_lg_body_loses_every_tag(lg_detail: dict[str, Any]) -> None:
    """실제로 소비 측에 나갔던 값. 태그가 하나도 남지 않고 문단은 줄로 남는다."""
    flattened = flatten_html(str(lg_detail["detailContext"]))

    assert "<" not in flattened
    assert "&nbsp;" not in flattened and " " not in flattened
    assert "&amp;" not in flattened
    # 태그로만 갈라져 있던 절이 각각 제 줄에 있다
    assert "■ 우리팀에서 하고 있는 일(주요 R&R)" in flattened.splitlines()
    assert "■ 수행 업무" in flattened.splitlines()
    # 빈 줄만 남은 줄은 없다
    assert all(line.strip() for line in flattened.splitlines())


def test_lg_requirements_becomes_a_line_per_item(lg_detail: dict[str, Any]) -> None:
    assert (
        flatten_html(str(lg_detail["requiredItem"])) == "학사(4년제) 이상\n관련직무 경력 7년 이상"
    )
