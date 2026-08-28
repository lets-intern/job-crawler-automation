"""본문 분류 테스트 (1.4.V).

Gemini 를 실제로 부르지 않는다. 응답은 가짜 클라이언트가 돌려주고, 확인하는 것은 넷이다 —
본문에 있는 값이 제 칸에 들어가는가, 본문에 없는 것이 빈 칸으로 남는가, **모델이 지어낸 값이
버려지는가**, 그리고 **판정 칸이 글자 일치 없이도 채워지는가.**

칸이 두 가지다. 뽑는 칸은 본문 글자를 그대로 옮기고, 판정 칸은 닫힌 목록에서 고른 뒤 근거
문장을 함께 낸다 (`app/classify/schema.py`).

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
from app.classify.grounding import NO_EVIDENCE, NOT_IN_BODY, NOT_IN_LIST, ground, in_body
from app.classify.schema import (
    CLASSIFY_FIELDS,
    EXTRACT_FIELDS,
    JUDGE_CHOICES,
    JUDGE_FIELDS,
    RESPONSE_FIELDS,
)
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
    return json.dumps({name: fields.get(name, "") for name in RESPONSE_FIELDS})


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
            requirements="API 연동 아키텍처, 웹/앱 서비스의 데이터 흐름, 시스템 연동에 대한 "
            "기술적 이해도가 높으신 분",
            hiring_process="서류전형 > 1차 인터뷰 > 2차 인터뷰 > 처우 협의 > 최종 합격 및 입사",
        )
    )

    assert "API 연동 아키텍처" in result.fields["requirements"]
    assert result.fields["hiring_process"].startswith("서류전형")
    assert result.dropped == []
    assert result.attempts == 1


async def test_the_columns_the_body_does_not_name_stay_empty() -> None:
    """본문에 없는 것은 빈 칸이다. 이것이 이 작업의 전제다."""
    result, _ = await classify(
        response(
            hiring_process="서류전형 > 1차 인터뷰 > 2차 인터뷰 > 처우 협의 > 최종 합격 및 입사"
        )
    )

    assert result.filled == ["hiring_process"]
    for name in CLASSIFY_FIELDS:
        if name != "hiring_process":
            assert result.fields[name] == "", name


async def test_a_value_that_is_not_in_the_body_is_thrown_away() -> None:
    """일부러 본문에 없는 것을 답하게 한다. 그럴듯해도 버려야 한다."""
    result, _ = await classify(
        response(
            work_location="서울 강남구 테헤란로 123",
            hiring_process="서류전형 > 1차 인터뷰 > 2차 인터뷰 > 처우 협의 > 최종 합격 및 입사",
        )
    )

    assert result.dropped == ["work_location"]
    assert result.reasons["work_location"] == NOT_IN_BODY
    assert result.fields["work_location"] == ""
    # 본문에 있는 값은 그대로 남는다. 한 칸이 틀렸다고 나머지를 버리지 않는다
    assert result.fields["hiring_process"].startswith("서류전형")
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
    result, client = await classify(
        "{ 이건 JSON 이 아니다",
        response(
            hiring_process="서류전형 > 1차 인터뷰 > 2차 인터뷰 > 처우 협의 > 최종 합격 및 입사"
        ),
    )

    assert result.attempts == 2
    assert result.fields["hiring_process"].startswith("서류전형")
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


def test_the_two_kinds_of_columns_add_up_to_the_eight() -> None:
    """칸이 늘거나 옮겨 다니면 여기서 걸린다."""
    assert set(EXTRACT_FIELDS) | set(JUDGE_FIELDS) == set(CLASSIFY_FIELDS)
    assert not set(EXTRACT_FIELDS) & set(JUDGE_FIELDS)


def test_the_judge_columns_have_a_closed_list() -> None:
    """목록을 정하지 않으면 같은 일이 사이트마다 다른 이름으로 쌓인다."""
    assert JUDGE_CHOICES["employment_type"] == ("정규직", "계약직", "인턴", "기타")
    assert JUDGE_CHOICES["career_level"] == ("신입", "경력", "무관")
    for values in JUDGE_CHOICES.values():
        assert "" not in values


async def test_a_judgement_does_not_need_the_words_to_be_in_the_body() -> None:
    """본문에 "경력" 이라고 적혀 있지 않다. 글자 일치를 요구하면 이 칸은 영원히 빈다."""
    result, _ = await classify(
        response(
            career_level="경력",
            career_level_evidence="Product Owner로서 5년 이상 경험이 있으신 분",
            employment_type="정규직",
            employment_type_evidence="정규직",
        )
    )

    assert result.fields["career_level"] == "경력"
    assert result.fields["employment_type"] == "정규직"
    assert result.dropped == []


async def test_a_judgement_without_evidence_in_the_body_is_thrown_away() -> None:
    """읽고 고른 것인지 지어낸 것인지 가를 방법이 근거 문장뿐이다."""
    result, _ = await classify(
        response(
            career_level="신입",
            career_level_evidence="신입 사원을 우대합니다",
        )
    )

    assert result.dropped == ["career_level"]
    assert result.reasons["career_level"] == NO_EVIDENCE
    assert result.fields["career_level"] == ""
    assert result.evidence == {}


async def test_a_judgement_with_no_evidence_at_all_is_thrown_away() -> None:
    result, _ = await classify(response(employment_type="정규직"))

    assert result.dropped == ["employment_type"]
    assert result.reasons["employment_type"] == NO_EVIDENCE


async def test_a_judgement_outside_the_list_is_thrown_away() -> None:
    """목록 밖 값이 한 번 들어오면 그 칸으로 거르는 소비 측이 조용히 그 건을 놓친다."""
    result, _ = await classify(
        response(employment_type="풀타임", employment_type_evidence="◆ 직원 유형")
    )

    assert result.dropped == ["employment_type"]
    assert result.reasons["employment_type"] == NOT_IN_LIST
    assert result.fields["employment_type"] == ""


async def test_the_evidence_comes_back_with_the_result() -> None:
    """표본 스무 건 표가 판정 칸마다 근거 문장을 적어야 한다 (1.8.V)."""
    result, _ = await classify(
        response(employment_type="정규직", employment_type_evidence="◆ 직원 유형")
    )

    assert result.evidence == {"employment_type": "◆ 직원 유형"}


async def test_the_prompt_carries_the_closed_list() -> None:
    """무엇 중에서 고르는지 모르는 채로 고르면 가장 가까운 값이 아니라 첫 값이 나온다."""
    _, client = await classify(response())

    prompt = client.calls[0]["contents"]
    for value in JUDGE_CHOICES["employment_type"]:
        assert value in prompt


async def test_the_response_schema_forces_the_list() -> None:
    """프롬프트로만 부탁하면 지킵니다가 아니라 대개 지킵니다가 된다."""
    _, client = await classify(response())

    schema = client.calls[0]["config"]["response_schema"]
    assert schema.model_fields["career_level"].annotation is not str


def test_the_enum_never_carries_an_empty_value() -> None:
    """Gemini 가 빈 값이 든 enum 을 400 으로 거절한다 (2026-08-26 스무 건 표본에서 확인).

    그때 스무 건이 전부 `api_error` 로 끝났다. 스키마가 잘못되면 본문을 보내기도 전에
    막히므로 토큰은 나가지 않지만, 그 사실을 아는 데 실행 한 번이 든다.
    """
    from typing import get_args

    from app.classify.schema import UNDECIDED, Classification

    for name in JUDGE_FIELDS:
        values = get_args(Classification.model_fields[name].annotation)
        assert values, name
        assert "" not in values, name
        assert UNDECIDED in values, name


async def test_undecided_is_stored_as_an_empty_column_and_is_not_counted_as_invented() -> None:
    """ "고를 수 없다" 는 답이다. 버린 것이 아니라 본문에 근거가 없다는 뜻이다."""
    from app.classify.schema import UNDECIDED

    result, _ = await classify(response(employment_type=UNDECIDED, career_level=UNDECIDED))

    assert result.fields["employment_type"] == ""
    assert result.dropped == []
    assert result.evidence == {}


async def test_the_prompt_offers_the_undecided_answer() -> None:
    """자리가 없으면 모델은 아무거나 고른다."""
    from app.classify.schema import UNDECIDED

    _, client = await classify(response())

    assert UNDECIDED in client.calls[0]["contents"]
