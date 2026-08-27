"""열한 사이트 응답을 대조해 확정한 칸이 정말 넷 이상에서 오는지 센다.

확정 기준은 하나다 — **넷 이상의 사이트가 주는 것만 칸으로 만든다.** 한 사이트만 가진 값을
칸으로 만들면 나머지 열 곳이 비는 칸이 하나 는다. 이 파일은 그 셈을 픽스처로 다시 해서,
표에 적힌 자리가 실제로 값을 내놓는지까지 확인한다.

"준다" 의 뜻을 좁게 잡았다. **그 값만 따로 꺼낼 수 있어야 준 것이다** — JSON 필드 하나이거나,
이름표가 붙은 DOM 요소 하나여야 한다. 본문 덩어리 안에 `■ 우대사항` 으로 섞여 있는 것은 세지
않는다. 세면 Push 2 가 텍스트를 잘라 채우게 되고, 그것이 PRD 가 막으려는 "억지로 채우기" 다.

확정한 표는 `.claude/tasks/todo/tasks-split-body-push1.md` 에 있다. 이 파일이 그 표다.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from bs4 import BeautifulSoup

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# 넷 미만이면 칸으로 만들지 않는다
MINIMUM_SITES = 4

JSON = "json"
CSS = "css"

# (칸, 사이트, 픽스처, 읽는 법, 자리)
#
# JSON 자리는 점 표기다. `*` 는 배열 전체를 훑는다 — `app/crawler/api_source.py` 와 같은
# 표기라 Push 2 가 이 문자열을 그대로 설정에 옮길 수 있다.
# CSS 자리는 상세 HTML 의 셀렉터다.
TABLE: tuple[tuple[str, str, str, str, str], ...] = (
    # 직군
    (
        "직군",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.jobNoticesDetail.jobGroupSh",
    ),
    ("직군", "현대자동차", "hyundai-detail-02800-20260825.json", JSON, "data.applyInfo.jdGroupNm"),
    (
        "직군",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.box-detail-item:has(.label:-soup-contains("직무")) .value',
    ),
    (
        "직군",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'dt:-soup-contains("모집분야") + dd',
    ),
    (
        "직군",
        "네이버",
        "naver-detail-30005299-20260826.html",
        CSS,
        '.card_info dt:-soup-contains("모집 분야") + dd',
    ),
    ("직군", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.jobPartName"),
    ("직군", "우아한형제들", "woowa-detail-R2607031-20260826.html", CSS, ".flag-tag button"),
    # 고용형태
    (
        "고용형태",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.box-detail-item:has(.label:-soup-contains("유형")) .value',
    ),
    (
        "고용형태",
        "네이버",
        "naver-detail-30005299-20260826.html",
        CSS,
        '.card_info dt:-soup-contains("근로 조건") + dd',
    ),
    ("고용형태", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.employeeTypeName"),
    (
        "고용형태",
        "우아한형제들",
        "woowa-detail-R2607031-20260826.html",
        CSS,
        ".flag-type span:nth-of-type(1)",
    ),
    # 경력 구분
    (
        "경력 구분",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.jobNoticesDetail.careerTypeName",
    ),
    (
        "경력 구분",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.channelCodeNm",
    ),
    (
        "경력 구분",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.box-detail-item:has(.label:-soup-contains("구분")) .value',
    ),
    (
        "경력 구분",
        "네이버",
        "naver-detail-30005299-20260826.html",
        CSS,
        '.card_info dt:-soup-contains("모집 경력") + dd',
    ),
    ("경력 구분", "우아한형제들", "woowa-detail-R2607031-20260826.html", CSS, ".flag-career"),
    # 근무지
    (
        "근무지",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.recList.*.locationName",
    ),
    ("근무지", "한화", "hanwha-detail-20260825.json", JSON, "data.item.unitDt.*.ruWorkpl"),
    (
        "근무지",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.workPlaceCodeNm",
    ),
    ("근무지", "삼성", "samsung-detail-20260825.json", JSON, "data.items.*.workPlaceKr"),
    (
        "근무지",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.box-detail-item:has(.label:-soup-contains("지역")) .value',
    ),
    (
        "근무지",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'dt:-soup-contains("지역") + dd',
    ),
    ("근무지", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.locationName"),
    # 모집인원
    ("모집인원", "LG", "lg-detail-20260825.json", JSON, "data.jobNoticesDetail.recList.*.numbers"),
    ("모집인원", "한화", "hanwha-detail-20260825.json", JSON, "data.item.unitDt.*.ruRcrtPrsn"),
    (
        "모집인원",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'dt:-soup-contains("인원") + dd',
    ),
    ("모집인원", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.displayRecruitCount"),
    # 주요 업무
    (
        "주요 업무",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.recList.*.detailContext",
    ),
    ("주요 업무", "한화", "hanwha-detail-20260825.json", JSON, "data.item.unitDt.*.ruDtlJob"),
    (
        "주요 업무",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.privJdDtl",
    ),
    ("주요 업무", "삼성", "samsung-detail-20260825.json", JSON, "data.items.*.taskKr"),
    (
        "주요 업무",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.detail-content-item:has(.detail-content-title:-soup-contains("About the job"))'
        " .detail-content-box",
    ),
    (
        "주요 업무",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'dt:-soup-contains("수행업무") + dd',
    ),
    ("주요 업무", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.workContentDesc"),
    # 우대 조건
    (
        "우대 조건",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.recList.*.preferredItem",
    ),
    (
        "우대 조건",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.prefReq",
    ),
    ("우대 조건", "삼성", "samsung-detail-20260825.json", JSON, "data.items.*.favorKr"),
    (
        "우대 조건",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.detail-content-item:has(.detail-content-title:-soup-contains("Preferred"))'
        " .detail-content-box",
    ),
    # 전형 절차
    (
        "전형 절차",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.jobNoticesDetail.recProcessInfo",
    ),
    ("전형 절차", "한화", "hanwha-detail-20260825.json", JSON, "data.item.rtExmProc"),
    (
        "전형 절차",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.procStep1Nm",
    ),
    (
        "전형 절차",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.detail-content-item:has(.detail-content-title:-soup-contains("Recruiting Process"))'
        " .detail-content-box",
    ),
    (
        "전형 절차",
        "롯데그룹",
        "lotte-detail-20260825.html",
        CSS,
        'p.hire-title:-soup-contains("전형절차") + ol.hire-step',
    ),
    (
        "전형 절차",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'th:-soup-contains("전형절차") + td',
    ),
    ("전형 절차", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.jobOfferProcessDesc"),
    # 기타
    (
        "기타",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.jobNoticesDetail.otherInfo",
    ),
    ("기타", "한화", "hanwha-detail-20260825.json", JSON, "data.item.rtEct"),
    ("기타", "현대자동차", "hyundai-detail-02800-20260825.json", JSON, "data.applyInfo.etc"),
    ("기타", "삼성", "samsung-detail-20260825.json", JSON, "data.result.etcKr"),
    (
        "기타",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.detail-content-item:has(.detail-content-title:-soup-contains("Please Read"))'
        " .detail-content-box",
    ),
    (
        "기타",
        "롯데그룹",
        "lotte-detail-20260825.html",
        CSS,
        'p.hire-title:-soup-contains("기타사항") + ul.hire-bul',
    ),
    (
        "기타",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'th:-soup-contains("기타사항") + td',
    ),
    # 모집 시작일
    (
        "모집 시작일",
        "LG",
        "lg-detail-20260825.json",
        JSON,
        "data.jobNoticesDetail.jobNoticesDetail.recStartDate",
    ),
    ("모집 시작일", "한화", "hanwha-detail-20260825.json", JSON, "data.item.rtAcptStrtDttm"),
    (
        "모집 시작일",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.appDispStDt",
    ),
    ("모집 시작일", "삼성", "samsung-detail-20260825.json", JSON, "data.result.startdate"),
    (
        "모집 시작일",
        "SK",
        "sk-detail-20260825.html",
        CSS,
        '.box-detail-item:has(.label:-soup-contains("지원 기간")) .value',
    ),
    ("모집 시작일", "롯데그룹", "lotte-detail-20260825.html", CSS, ".date-detail"),
    (
        "모집 시작일",
        "두산",
        "doosan-detail-1000361539-20260826.html",
        CSS,
        'th:-soup-contains("채용공고") + td',
    ),
    (
        "모집 시작일",
        "네이버",
        "naver-detail-30005299-20260826.html",
        CSS,
        '.card_info dt:-soup-contains("모집 기간") + dd',
    ),
    (
        "모집 시작일",
        "우아한형제들",
        "woowa-list-api-20260825.json",
        JSON,
        "data.list.*.recruitOpenDate",
    ),
)

# 셋뿐이라 칸으로 만들지 않는다. PRD 의 후보였다 — 열한 곳으로 다시 세어 떨어졌다.
# 이 셋의 값은 지금처럼 `body` 에 남는다
REJECTED: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "조직 소개",
        "현대자동차",
        "hyundai-detail-02800-20260825.json",
        JSON,
        "data.applyInfo.aboutTeamNtc",
    ),
    ("조직 소개", "삼성", "samsung-detail-20260825.json", JSON, "data.result.introKr"),
    ("조직 소개", "카카오", "kakao-list-api-20260825.json", JSON, "jobList.*.introduction"),
)

# 확정한 새 칸과 그 값을 주는 사이트 수. 표가 바뀌면 여기도 같이 바뀐다
EXPECTED_COUNTS = {
    "직군": 7,
    "고용형태": 4,
    "경력 구분": 5,
    "근무지": 7,
    "모집인원": 4,
    "주요 업무": 7,
    "우대 조건": 4,
    "전형 절차": 7,
    "기타": 7,
    "모집 시작일": 9,
}


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


def _walk(data: Any, path: str) -> list[Any]:
    """점 표기 경로를 훑는다. `*` 는 배열 전체다. 빈 값은 떨어진다."""
    current: list[Any] = [data]
    for part in path.split("."):
        following: list[Any] = []
        for node in current:
            if part == "*":
                if isinstance(node, list):
                    following.extend(node)
            elif isinstance(node, dict) and part in node:
                following.append(node[part])
        current = following
    return [node for node in current if node not in (None, "", [], {})]


def resolve(fixture: str, kind: str, path: str) -> list[str]:
    """그 자리가 실제로 내놓는 값. 비어 있으면 빈 목록이다."""
    if kind == JSON:
        return [str(value) for value in _walk(_load(fixture), path)]
    found = (node.get_text(" ", strip=True) for node in _soup(fixture).select(path))
    return [text for text in found if text]


def counted(rows: tuple[tuple[str, str, str, str, str], ...]) -> dict[str, list[str]]:
    tally: dict[str, list[str]] = {}
    for column, site, fixture, kind, path in rows:
        if resolve(fixture, kind, path):
            tally.setdefault(column, []).append(site)
        else:
            tally.setdefault(column, [])
    return tally


def test_every_place_in_the_table_actually_holds_a_value() -> None:
    """표에 적힌 자리가 하나라도 비면 그 칸의 셈이 틀린 것이다."""
    empty = [
        f"{column}/{site}: {path}"
        for column, site, fixture, kind, path in TABLE
        if not resolve(fixture, kind, path)
    ]

    assert empty == []


def test_no_confirmed_column_comes_from_fewer_than_four_sites() -> None:
    """확정 기준 그대로다. 넷 미만인 칸이 하나라도 있으면 표를 다시 만든다."""
    tally = counted(TABLE)

    thin = {column: sites for column, sites in tally.items() if len(sites) < MINIMUM_SITES}
    assert thin == {}


def test_the_counts_are_the_ones_written_in_the_task_file() -> None:
    """작업 파일의 표와 같은 숫자여야 한다. 다음 Push 가 그 표를 보고 매핑한다."""
    tally = counted(TABLE)

    assert {column: len(sites) for column, sites in tally.items()} == EXPECTED_COUNTS


def test_the_team_introduction_falls_short_of_four_sites() -> None:
    """PRD 의 후보였다. 셋뿐이라 칸으로 만들지 않고 `body` 에 남긴다."""
    tally = counted(REJECTED)

    assert len(tally["조직 소개"]) == 3
    assert len(tally["조직 소개"]) < MINIMUM_SITES
