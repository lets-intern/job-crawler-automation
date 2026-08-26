"""열한 사이트의 새 매핑을 픽스처에 돌려 칸별로 확인한다 (2.3.V, 2.4.V).

Push 1 은 어느 사이트가 어느 칸을 주는지 세어 칸을 확정했다(`tests/test_split_body_columns.py`).
이 파일은 그 다음 질문에 답한다 — **설정에 적힌 자리가 실제로 그 칸을 채우는가.**

기준은 2026-08-26 에 넓어졌다. 응답에 별도 필드로 있는 값은 최대한 매핑하고, 갈 칸이 없는
것은 기타(`etc_info`)로 모은다. 매핑하지 않은 값은 저장되지 않아 다시 얻을 길이 없기
때문이다 (`.claude/tasks/todo/tasks-split-body-push2.md`).

빈 칸도 단언한다. 사이트가 주지 않는 값을 다른 값으로 채우는 것이 이 Push 가 고치는 버그이고,
빈 칸을 단언하지 않으면 그 버그가 다시 들어와도 테스트가 웃으며 지나간다.

실사이트에 나가지 않는다. 열한 사이트의 응답이 전부 `tests/fixtures/` 에 있다.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from app.crawler.api_source import build_detail, build_items
from app.crawler.parser import parse_detail
from app.selector.api_schema import validate_api_config
from app.selector.schema import DETAIL_FIELDS, validate_selectors

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SEEDS = pathlib.Path(__file__).parent.parent / "seeds" / "site-configs-20260826.json"

SEED_DOC: dict[str, Any] = json.loads(SEEDS.read_text(encoding="utf-8"))
CONFIGS: dict[str, dict[str, Any]] = {entry["name"]: entry for entry in SEED_DOC["crawlers"]}

JSON = "json"
HTML = "html"

# 사이트마다 상세를 어디서 읽는지. `json` 이면 API 설정, `html` 이면 셀렉터다
DETAIL_SOURCE: dict[str, tuple[str, str]] = {
    "LG": (JSON, "lg-detail-20260825.json"),
    "한화": (JSON, "hanwha-detail-20260825.json"),
    "삼성": (JSON, "samsung-detail-20260825.json"),
    "현대자동차": (JSON, "hyundai-detail-02800-20260825.json"),
    "SK": (HTML, "sk-detail-20260825.html"),
    "롯데그룹": (HTML, "lotte-detail-20260825.html"),
    "두산": (HTML, "doosan-detail-1000361539-20260826.html"),
    "네이버": (HTML, "naver-detail-30005299-20260826.html"),
    "토스": (HTML, "toss-detail-7827417003-20260826.html"),
    "카카오": (HTML, "kakao-detail-P-14503-20260826.html"),
    "우아한형제들": (HTML, "woowa-detail-R2607031-20260826.html"),
}

# 상세가 못 주는 칸을 목록이 나르는 사이트. 그 목록 픽스처다
# (`app/crawler/runner.py` 의 `_record`)
LIST_SOURCE: dict[str, str] = {
    "카카오": "kakao-list-api-20260825.json",
    "우아한형제들": "woowa-list-api-20260825.json",
}

# 사이트마다 채워지는 칸. 여기 없는 칸은 비어야 한다.
#
# `title` 과 `body` 는 열한 곳 다 채우므로 적지 않는다 — 비면 수집 자체가 실패다
# (`app/crawler/parser.py` 의 `REQUIRED_DETAIL_FIELDS`).
FILLED: dict[str, frozenset[str]] = {
    "LG": frozenset(
        {
            "requirements",
            "deadline",
            "department",
            "company",
            "start_date",
            "job_category",
            "career_level",
            "work_location",
            "headcount",
            "duties",
            "preferred",
            "hiring_process",
            "etc_info",
        }
    ),
    "한화": frozenset(
        {
            "requirements",
            "deadline",
            "company",
            "start_date",
            "work_location",
            "headcount",
            "duties",
            "hiring_process",
            "etc_info",
        }
    ),
    "삼성": frozenset(
        {
            "requirements",
            "company",
            "start_date",
            "work_location",
            "duties",
            "preferred",
            "etc_info",
        }
    ),
    "현대자동차": frozenset(
        {
            "requirements",
            "deadline",
            "department",
            "start_date",
            "job_category",
            "career_level",
            "work_location",
            "duties",
            "preferred",
            "hiring_process",
            "etc_info",
        }
    ),
    "SK": frozenset(
        {
            "requirements",
            "deadline",
            "company",
            "start_date",
            "job_category",
            "employment_type",
            "career_level",
            "work_location",
            "duties",
            "preferred",
            "hiring_process",
            "etc_info",
        }
    ),
    "롯데그룹": frozenset(
        {"requirements", "deadline", "company", "start_date", "hiring_process", "etc_info"}
    ),
    "두산": frozenset(
        {
            "requirements",
            "deadline",
            "company",
            "start_date",
            "job_category",
            "work_location",
            "headcount",
            "duties",
            "hiring_process",
            "etc_info",
        }
    ),
    "네이버": frozenset(
        {"deadline", "company", "start_date", "job_category", "employment_type", "career_level"}
    ),
    "토스": frozenset({"deadline"}),
    "카카오": frozenset(
        {
            "requirements",
            "deadline",
            "company",
            "start_date",
            "job_category",
            "employment_type",
            "work_location",
            "headcount",
            "duties",
            "hiring_process",
            "etc_info",
        }
    ),
    "우아한형제들": frozenset(
        {"deadline", "start_date", "job_category", "employment_type", "career_level"}
    ),
}

SITES = tuple(DETAIL_SOURCE)


def _payload(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def collected(site: str) -> dict[str, str]:
    """그 사이트의 설정으로 픽스처에서 뽑은 칸별 값. 실행이 `raw_jobs` 에 싣는 것과 같다."""
    entry = CONFIGS[site]
    kind, fixture = DETAIL_SOURCE[site]
    if kind == JSON:
        config = validate_api_config(entry["api_config"]).detail_config()
        fields = dict(build_detail(_payload(fixture), config).fields)
    else:
        selectors = validate_selectors(entry["selectors"]).detail
        html = (FIXTURES / fixture).read_text(encoding="utf-8")
        fields = dict(parse_detail(html, selectors).fields)

    carried = _carried(site)
    return {name: fields.get(name, "") or carried.get(name, "") for name in DETAIL_FIELDS}


def _carried(site: str) -> dict[str, str]:
    """목록이 나르는 값. 그런 사이트가 아니면 빈 값이다."""
    if site not in LIST_SOURCE:
        return {}
    config = validate_api_config(CONFIGS[site]["api_config"]).list_config()
    listing = build_items(_payload(LIST_SOURCE[site]), config)
    return dict(listing.items[0].extra)


def test_every_site_in_the_table_has_a_config() -> None:
    """설정·픽스처·표가 같은 열한 곳을 가리키는지. 하나가 빠지면 조용히 안 돌아간다."""
    assert set(CONFIGS) == set(SITES)
    assert set(FILLED) == set(SITES)


@pytest.mark.parametrize("site", SITES)
def test_the_config_passes_its_own_schema(site: str) -> None:
    """저장하기 전에 열한 개가 다 스키마를 지나는지 본다."""
    entry = CONFIGS[site]
    if "api_config" in entry:
        validate_api_config(entry["api_config"])
    if "selectors" in entry:
        validate_selectors(entry["selectors"])


@pytest.mark.parametrize("site", SITES)
def test_the_columns_the_site_gives_are_filled(site: str) -> None:
    values = collected(site)

    empty = sorted(name for name in FILLED[site] if not values[name].strip())
    assert empty == [], f"{site} 가 준다고 적힌 칸이 비었다"


@pytest.mark.parametrize("site", SITES)
def test_the_columns_the_site_does_not_give_stay_empty(site: str) -> None:
    """빈 칸이 다른 값으로 채워지는 것이 이 Push 가 고치는 버그다."""
    values = collected(site)
    expected_empty = set(DETAIL_FIELDS) - FILLED[site] - {"title", "body"}

    filled = sorted(name for name in expected_empty if values[name].strip())
    assert filled == [], f"{site} 가 주지 않는 칸에 값이 들어갔다"


@pytest.mark.parametrize("site", SITES)
def test_the_title_and_the_body_are_never_empty(site: str) -> None:
    values = collected(site)

    assert values["title"].strip(), site
    assert values["body"].strip(), site


def test_hanwha_no_longer_puts_the_workplace_in_the_department() -> None:
    """이 Push 를 시작하게 만든 버그다. 한화에는 부서 개념이 없다."""
    values = collected("한화")

    assert values["department"] == ""
    assert values["work_location"] == "본사(서울 63빌딩)"


def test_sk_no_longer_puts_the_job_in_the_department() -> None:
    """자리(nth-child)로 잡은 상자가 직무였다. 이름표로 바꾸면서 제 칸으로 보냈다."""
    values = collected("SK")

    assert values["department"] == ""
    assert values["job_category"] == "IT - IT 기획"
    assert values["employment_type"] == "Permanent"
    assert values["career_level"] == "Experienced"


def test_naver_no_longer_puts_the_field_in_the_department() -> None:
    """모집 부서가 'NAVER' 즉 계열사다. 부서가 아니라 회사로 간다."""
    values = collected("네이버")

    assert values["department"] == ""
    assert values["company"].strip() == "NAVER"
    assert values["job_category"].strip() == "Tech"


def test_doosan_reads_its_deadline_from_the_label_not_the_row_number() -> None:
    """자리로 잡고 있어서 '지원자 개별일정' 이 마감일로 들어오고 있었다."""
    values = collected("두산")

    assert values["deadline"].strip() == "2026-07-15 ~ 2026-08-31"
    assert values["company"].strip() == "매거진"


def test_woowa_splits_the_flag_that_held_two_values() -> None:
    """`.flag-type` 하나에 고용형태와 마감일이 같이 있었다."""
    values = collected("우아한형제들")

    assert values["employment_type"] == "기간제"
    assert values["deadline"] == "영입 종료시"


def test_toss_body_is_the_posting_and_not_the_navigation() -> None:
    """`.p-container__inner` 가 상단 내비게이션을 먼저 잡고 있었다."""
    values = collected("토스")

    assert "토스인컴" in values["body"]
    assert not values["body"].startswith("계열사 소개")


def test_kakao_gets_from_its_list_what_its_detail_cannot_split() -> None:
    """상세 문서의 본문은 한 덩어리다. 같은 값이 목록 API 에 별도 필드로 있다."""
    values = collected("카카오")

    assert values["job_category"] == "서비스비즈"
    assert values["duties"].startswith("- 카카오비즈니스와 외부 제휴사 간")
    # 상세 문서가 이름표로 주는 것은 상세에서 읽는다
    assert values["employment_type"] == "정규직"
    assert values["work_location"] == "판교"


def test_hyundai_reads_all_seven_process_steps() -> None:
    """한 자리만 읽으면 전형 절차가 '지원서 접수' 하나로 끝난다."""
    values = collected("현대자동차")

    assert values["hiring_process"].splitlines()[0] == "지원서 접수"
    assert "최종합격" in values["hiring_process"]


def test_the_leftovers_that_have_no_column_go_to_the_etc_column() -> None:
    """갈 칸이 없는 값은 버리지 않는다. 매핑하지 않은 값은 저장되지 않는다."""
    assert "1:1 문의하기" in collected("한화")["etc_info"]
    assert "제출방" in collected("LG")["etc_info"]
    assert "삼성채용 홈페이지" in collected("삼성")["etc_info"]


def test_the_requirements_and_the_preferred_are_no_longer_one_column() -> None:
    """사이트가 이미 나눠서 주는 것을 도로 합치고 있었다."""
    hyundai = collected("현대자동차")
    samsung = collected("삼성")

    assert hyundai["requirements"] != hyundai["preferred"]
    assert "박사" in hyundai["preferred"]
    assert samsung["requirements"] != samsung["preferred"]
