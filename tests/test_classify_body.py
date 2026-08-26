"""본문 분류 테스트 (1.4.V).

Gemini 를 실제로 부르지 않는다. 응답은 가짜 클라이언트가 돌려주고, 확인하는 것은 셋이다 —
본문에 있는 값이 제 칸에 들어가는가, 본문에 없는 것이 빈 칸으로 남는가, **모델이 지어낸 값이
버려지는가.**

본문은 저장된 픽스처에서 그 사이트의 설정으로 뽑는다. 손으로 지어낸 본문에 돌리면 실제
사이트의 글머리표와 줄바꿈을 못 보고 지나간다. 실사이트에 나가지 않는다.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.classify.classifier import (
    MAX_BODY_CHARS,
    ClassifyError,
    build_prompt,
    classify_body,
)
from app.classify.grounding import ground, in_body
from app.classify.schema import CLASSIFY_FIELDS
from app.config import Settings
from app.crawler.parser import parse_detail
from app.selector.schema import validate_selectors
from tests.test_selector_generator import FakeClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SEEDS = pathlib.Path(__file__).parent.parent / "seeds" / "site-configs-20260826.json"

CONFIGS = {
    entry["name"]: entry for entry in json.loads(SEEDS.read_text(encoding="utf-8"))["crawlers"]
}


def body_of(site: str, fixture: str) -> str:
    """그 사이트의 셀렉터로 픽스처에서 뽑은 본문. 실행이 `raw_jobs` 에 싣는 것과 같다."""
    selectors = validate_selectors(CONFIGS[site]["selectors"]).detail
    html = (FIXTURES / fixture).read_text(encoding="utf-8")
    return parse_detail(html, selectors).fields["body"]


BODY = body_of("카카오", "kakao-detail-P-14503-20260826.html")


def response(**fields: str) -> str:
    return json.dumps({name: fields.get(name, "") for name in CLASSIFY_FIELDS})


def settings_with_key() -> Settings:
    return Settings(gemini_api_key="테스트키", gemini_model="gemini-3.5-flash")


async def classify(*texts: str, body: str = BODY) -> tuple:
    client = FakeClient(*texts)
    result = await classify_body(body, settings=settings_with_key(), client=client)
    return result, client


def test_the_fixture_body_is_a_real_posting() -> None:
    """본문을 못 뽑으면 아래 테스트가 전부 빈 문자열을 상대로 웃으며 지나간다."""
    assert "◆ 지원자격" in BODY
    assert len(BODY) > 500


async def test_the_values_the_body_carries_land_in_their_columns() -> None:
    result, _ = await classify(
        response(
            employment_type="정규직",
            headcount="0 명",
            requirements="API 연동 아키텍처, 웹/앱 서비스의 데이터 흐름, 시스템 연동에 대한 "
            "기술적 이해도가 높으신 분",
            hiring_process="서류전형 > 1차 인터뷰 > 2차 인터뷰 > 처우 협의 > 최종 합격 및 입사",
        )
    )

    assert result.fields["employment_type"] == "정규직"
    assert result.fields["headcount"] == "0 명"
    assert "API 연동 아키텍처" in result.fields["requirements"]
    assert result.fields["hiring_process"].startswith("서류전형")
    assert result.dropped == []
    assert result.attempts == 1


async def test_the_columns_the_body_does_not_name_stay_empty() -> None:
    """본문에 없는 것은 빈 칸이다. 이것이 이 작업의 전제다."""
    result, _ = await classify(response(employment_type="정규직"))

    assert result.filled == ["employment_type"]
    for name in CLASSIFY_FIELDS:
        if name != "employment_type":
            assert result.fields[name] == "", name


async def test_a_value_that_is_not_in_the_body_is_thrown_away() -> None:
    """일부러 본문에 없는 것을 답하게 한다. 그럴듯해도 버려야 한다."""
    result, _ = await classify(
        response(
            work_location="서울 강남구 테헤란로 123",
            career_level="신입 및 경력 3년 이상",
            employment_type="정규직",
        )
    )

    assert sorted(result.dropped) == ["career_level", "work_location"]
    assert result.fields["work_location"] == ""
    assert result.fields["career_level"] == ""
    # 본문에 있는 값은 그대로 남는다. 한 칸이 틀렸다고 나머지를 버리지 않는다
    assert result.fields["employment_type"] == "정규직"
    assert "버린 칸" in " ".join(result.notes)


async def test_a_column_is_dropped_whole_when_one_of_its_lines_is_invented() -> None:
    """절반만 사실인 값은 읽는 쪽이 어디까지 믿어야 할지 알 수 없다."""
    result, _ = await classify(
        response(preferred="POS(포스), 키오스크, 테이블오더 등 오프라인 로컬 솔루션\n영어 능통자")
    )

    assert result.dropped == ["preferred"]
    assert result.fields["preferred"] == ""


async def test_a_reflowed_quote_still_counts_as_being_in_the_body() -> None:
    """줄바꿈과 글머리표가 달라진 것을 지어냈다고 하면 멀쩡한 값이 버려진다."""
    result, _ = await classify(
        response(duties="- 카카오비즈니스와 외부 제휴사 간 사업자 데이터 연동 구조 기획 및 설계")
    )

    assert result.dropped == []
    assert result.fields["duties"].startswith("- 카카오비즈니스")


async def test_a_column_the_schema_does_not_have_is_refused() -> None:
    client = FakeClient(json.dumps({"salary": "협의"}))

    with pytest.raises(ClassifyError) as caught:
        await classify_body(BODY, settings=settings_with_key(), client=client)

    assert caught.value.reason == "unknown_field"
    # 내용의 문제라 다시 묻지 않는다
    assert len(client.calls) == 1


async def test_a_broken_response_is_asked_once_more() -> None:
    result, client = await classify("{ 이건 JSON 이 아니다", response(employment_type="정규직"))

    assert result.attempts == 2
    assert result.fields["employment_type"] == "정규직"
    assert len(client.calls) == 2


async def test_it_gives_up_after_the_second_broken_response() -> None:
    client = FakeClient("깨진 응답", "여전히 깨진 응답")

    with pytest.raises(ClassifyError) as caught:
        await classify_body(BODY, settings=settings_with_key(), client=client)

    assert caught.value.reason == "unparsable"
    assert len(client.calls) == 2


async def test_an_empty_body_never_reaches_the_model() -> None:
    client = FakeClient(response())

    with pytest.raises(ClassifyError) as caught:
        await classify_body("   ", settings=settings_with_key(), client=client)

    assert caught.value.reason == "empty_body"
    assert client.calls == []


async def test_only_the_body_is_sent() -> None:
    """원본 HTML 도 페이지도 보내지 않는다 (`.claude/rules/llm.md`)."""
    _, client = await classify(response())

    prompt = client.calls[0]["contents"]
    assert BODY in prompt
    assert "<html" not in prompt


def test_a_body_over_the_cap_is_cut_and_the_cut_is_written_down() -> None:
    prompt, notes = build_prompt("가" * (MAX_BODY_CHARS + 500))

    assert "가" * MAX_BODY_CHARS in prompt
    assert "가" * (MAX_BODY_CHARS + 1) not in prompt
    assert notes and str(MAX_BODY_CHARS) in notes[0]


async def test_the_call_reports_its_tokens_and_latency() -> None:
    """공고마다 붙는 호출이라 이 숫자가 없으면 비용 질문에 답할 수 없다."""
    result, _ = await classify(response())

    assert result.usage.model == "gemini-3.5-flash"
    assert result.usage.input_tokens == 4321
    assert result.usage.output_tokens == 120
    assert result.usage.latency_ms >= 0


def test_grounding_ignores_bullets_and_spacing_but_not_missing_words() -> None:
    body = "◆ 우대사항\n\n• SQL, Tableau 등 데이터 도구를 활용해 본 경험"

    assert in_body("- SQL, Tableau 등 데이터 도구를 활용해 본 경험", body)
    assert in_body("SQL Tableau 등 데이터 도구를 활용해 본 경험", body)
    assert not in_body("Python 을 활용해 본 경험", body)


def test_grounding_keeps_an_empty_column_empty_without_calling_it_invented() -> None:
    grounded = ground({name: "" for name in CLASSIFY_FIELDS}, "본문")

    assert grounded.dropped == []
    assert set(grounded.fields) == set(CLASSIFY_FIELDS)
